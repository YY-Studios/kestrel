"""Kestrel 매매 엔진 워커 — 자동매매의 핵심.

별도 프로세스로 항상 돌면서 시세를 감시한다(첫 슬라이스: 시세 폴링 + 로그).
지표·신호 판단·주문·DB는 다음 슬라이스에서 채운다.

실행: `uv run python -m worker.main`  (engine/ 디렉터리에서)
종료: Ctrl+C (SIGINT) 또는 docker stop (SIGTERM) — 둘 다 현재 주기 마무리 후 깨끗하게 멈춘다.
"""

from __future__ import annotations

import logging
import os
import signal
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType

from broker_client import KisClient, KisConfig

from worker.config import get_settings
from worker.db import (
    SignalRecorder,
    get_client,
    get_held_symbols,
    get_open_positions,
    load_strategy_settings,
    load_watchlist,
)
from worker.cache import DEFAULT_TTL_SECONDS, DailyPriceCache
from worker.entry_profile import build_evaluator, describe, profile_active
from worker.market_hours import is_market_open
from worker.execution import OrderExecutor
from worker.loop import parse_watchlist, resolve_watchlist_override, run_poll_loop
from worker.orders import OrderConfig
from worker.strategy_config import DEFAULTS, evaluate_overrides, validate_strategy_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("kestrel.engine")

# 토큰 캐시는 레포 루트의 .gitignore된 파일(스크립트와 공유 → 발급 1분 1회 제한 회피).
_TOKEN_CACHE = Path(__file__).resolve().parents[2] / ".kis_token_cache.json"
# 감시 종목: Supabase watchlist 테이블에서 로드. DB 비었/연결 실패 시 폴백(아래 기본값 + env WATCHLIST).
_DEFAULT_WATCHLIST = "NAS:AAPL"

_running = True


def _handle_stop(signum: int, _frame: FrameType | None) -> None:
    global _running
    logger.info("종료 신호 수신(%s). 현재 주기 마무리 후 멈춥니다.", signum)
    _running = False


def main() -> None:
    # .env를 os.environ으로 로드 — LIVE_ORDERS·ENTRY_PROFILE·WATCHLIST_OVERRIDE·TOTAL_CAPITAL은
    # os.environ으로 읽으므로, .env만으로 동작하게 한다. override=False라 실제 셸 env가 우선.
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    settings = get_settings()
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    # Supabase 클라이언트 1개로 워치리스트 로드 + 신호 로그 기록. 실패 시 폴백·기록 생략(루프는 계속).
    fallback = parse_watchlist(os.environ.get("WATCHLIST", _DEFAULT_WATCHLIST).split(","))
    try:
        sb = get_client()
    except Exception as exc:
        logger.warning("Supabase 연결 실패(%s) — 폴백 워치리스트, 신호 로그 생략", type(exc).__name__)
        sb = None
    # 검증 통제: WATCHLIST_OVERRIDE가 있으면 DB를 무시하고 지정 종목만(1종목 통제용).
    # 미설정 시 기존 동작(DB 우선, 실패 시 폴백) 그대로 — 평상시 영향 0.
    override = resolve_watchlist_override(os.environ.get("WATCHLIST_OVERRIDE"))
    if override:
        watchlist = override
        logger.warning("⚠️  워치리스트 강제 지정(WATCHLIST_OVERRIDE) — DB 무시: %s", watchlist)
    else:
        watchlist = load_watchlist(sb, fallback) if sb is not None else fallback
    recorder = SignalRecorder(sb) if sb is not None else None

    client = KisClient(
        KisConfig(
            app_key=settings.kis_app_key,
            app_secret=settings.kis_app_secret,
            account_no=settings.kis_account_no,
            is_paper=settings.kis_is_paper,
        ),
        token_cache_path=str(_TOKEN_CACHE),
    )

    # 전략설정: 시작 시 1회 DB 로드 → 진입 임계값·손절/익절%·자금 배분에 주입.
    #   - 못 읽으면(테이블 없음/실패) 전략 코드 기본값으로 폴백(현 동작 유지, 죽지 않음).
    #   - DB 값은 strategy_config에서 범위 재검증됨(이상값은 필드별 기본값 대체).
    loaded = load_strategy_settings(sb) if sb is not None else None
    strat = loaded if loaded is not None else validate_strategy_settings(None)
    strat_source = "DB" if loaded is not None else "기본값"
    # 자금은 검증용 env(TOTAL_CAPITAL)가 있으면 그게 우선(검증 통제), 없으면 DB/기본값.
    env_capital = os.environ.get("TOTAL_CAPITAL", "").strip()
    total_capital = float(env_capital) if env_capital else float(strat["total_capital"])

    # 주문 실행기: 기본 드라이런, LIVE_ORDERS=true AND paper일 때만 실주문(executor가 자체 판단).
    # 보유 종목은 positions(status=open)에서 읽어 시작 시점에 채운다(주문 시 세션 내 갱신).
    live = os.environ.get("LIVE_ORDERS", "").strip().lower() == "true"
    order_config = OrderConfig(total_capital=total_capital, max_positions=int(strat["max_positions"]))
    held_symbols: set[str] = get_held_symbols(sb) if sb is not None else set()
    executor = OrderExecutor(
        broker=client,
        db_client=sb,
        config=order_config,
        live=live,
        is_paper=settings.kis_is_paper,
        held_symbols=held_symbols,
        target_pct=float(strat["take_profit_pct"]),
        stop_pct=float(strat["stop_loss_pct"]),
    )

    # 진입 판단기: DB 전략설정(진입 임계값)을 base로 깔고, 검증용 완화 env가 있으면 그 위에 우선.
    evaluator = build_evaluator(os.environ, base_overrides=evaluate_overrides(strat))
    logger.info(
        "전략설정 적용: RSI %g · 눌림 %g~%g%% · 반등 %d/3 · 익절 +%g%% · 손절 −%g%% · 자금 $%g · 최대 %d종목 (출처: %s)",
        strat["rsi_threshold"], strat["pullback_min"] * 100, strat["pullback_max"] * 100,
        strat["rebound_required"], strat["take_profit_pct"] * 100, strat["stop_loss_pct"] * 100,
        total_capital, strat["max_positions"], strat_source,
    )
    if profile_active(os.environ):
        logger.warning("=" * 60)
        logger.warning("⚠️  검증 프로필 활성 — 진입 조건이 완화됨(위 전략설정보다 우선): %s", describe(os.environ))
        logger.warning("⚠️  통제된 LIVE 진입 검증용. 실계좌(real) 아님이 맞는지 확인하세요(paper=%s).", settings.kis_is_paper)
        logger.warning("=" * 60)

    # 일봉 캐시: TTL 안에선 재사용해 KIS 호출을 줄인다(현재가는 실시간이라 캐싱 안 함).
    daily_ttl = float(os.environ.get("DAILY_CACHE_TTL_SEC", str(DEFAULT_TTL_SECONDS)))
    daily_cache = DailyPriceCache(ttl_seconds=daily_ttl)

    # 장 시간 폴링: 기본은 미국 정규장(ET 09:30~16:00 평일)에만. IGNORE_MARKET_HOURS=true면 항상(개발용).
    ignore_market = os.environ.get("IGNORE_MARKET_HOURS", "").strip().lower() == "true"
    market_is_open = None if ignore_market else (lambda: is_market_open(datetime.now(timezone.utc)))

    logger.info(
        "매매 엔진 시작 (paper=%s, interval=%ss, watchlist=%s, 신호로그=%s, 주문모드=%s, 일봉캐시TTL=%gs, 폴링=%s)",
        settings.kis_is_paper,
        settings.poll_interval_seconds,
        watchlist or "(비어 있음)",
        "on" if recorder else "off",
        executor.mode,
        daily_ttl,
        "⚠️ 장 시간 무시(개발용)" if ignore_market else "장 시간만(장외 대기)",
    )

    try:
        run_poll_loop(
            client,
            watchlist,
            settings.poll_interval_seconds,
            should_run=lambda: _running,
            evaluator=evaluator,
            recorder=recorder,
            executor=executor,
            position_loader=(lambda: get_open_positions(sb)) if sb is not None else None,
            daily_cache=daily_cache,
            market_is_open=market_is_open,
        )
    finally:
        client.close()

    logger.info("매매 엔진 정상 종료")


if __name__ == "__main__":
    main()
