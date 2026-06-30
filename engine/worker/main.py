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
from pathlib import Path
from types import FrameType

from broker_client import KisClient, KisConfig

from worker.config import get_settings
from worker.db import SignalRecorder, get_client, get_held_symbols, load_watchlist
from worker.loop import parse_watchlist, run_poll_loop
from worker.orders import OrderConfig

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

    # 주문 결정은 이번 단계까지 드라이런(로그만). 총 투자금액은 env로(기본 10000).
    # 보유 종목은 positions(status=open)에서 읽어 시작 시점에 채운다(주문 시 실시간 갱신은 다음 단계).
    order_config = OrderConfig(total_capital=float(os.environ.get("TOTAL_CAPITAL", "10000")))
    held_symbols: set[str] = get_held_symbols(sb) if sb is not None else set()

    logger.info(
        "매매 엔진 시작 (paper=%s, interval=%ss, watchlist=%s, 신호로그=%s, 주문=드라이런)",
        settings.kis_is_paper,
        settings.poll_interval_seconds,
        watchlist or "(비어 있음)",
        "on" if recorder else "off",
    )

    try:
        run_poll_loop(
            client,
            watchlist,
            settings.poll_interval_seconds,
            should_run=lambda: _running,
            recorder=recorder,
            order_config=order_config,
            held_symbols=held_symbols,
        )
    finally:
        client.close()

    logger.info("매매 엔진 정상 종료")


if __name__ == "__main__":
    main()
