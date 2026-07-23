"""시세 폴링 루프 — 진입 판단 + 포지션 점검(손절·익절·분할 2·3차).

워치리스트 종목마다 일봉+현재가를 broker로 받아 evaluate_entry로 진입 신호를 판단하고,
보유 포지션은 손절 → 익절 → 추가매수 순으로 점검한다(청산 우선 — 물타기 방지).
주문 실행·기록은 executor(execution)에 위임하고, 기본은 드라이런이다.

KIS 호출은 broker-client(KisClient)만 경유한다. 두뇌(indicators)는 순수 함수 그대로 재사용.
무한 루프는 engine에만 둔다(ARCHITECTURE).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Protocol

from worker.execution import ORDER_TO_PRICE_EXCD
from worker.indicators import EntryResult, evaluate_entry
from worker.market_hours import seconds_until_open
from worker.orders import MAX_TRANCHE_STAGE

logger = logging.getLogger("kestrel.engine")

# 장외 대기 기본 간격(초)과 상태 로그 최소 간격(스팸 방지).
DEFAULT_IDLE_SLEEP = 60.0
DEFAULT_IDLE_LOG_INTERVAL = 1800.0  # 30분


def _interruptible_sleep(
    total: float, chunk: float, should_run: Callable[[], bool], sleep: Callable[[float], None]
) -> None:
    """total초를 chunk 단위로 나눠 자며, 매 조각마다 should_run을 확인해 종료에 빠르게 반응한다."""
    step = max(chunk, 0.1)
    slept = 0.0
    while slept < total and should_run():
        sleep(min(step, total - slept))
        slept += step


class Broker(Protocol):
    """루프가 필요로 하는 broker의 최소 인터페이스(테스트는 가짜로 대체)."""

    def get_overseas_daily_prices(self, exchange: str, symbol: str) -> list[tuple[str, float]]: ...
    def get_overseas_price(self, exchange: str, symbol: str) -> dict: ...


# 판단 함수 타입(테스트에서 주입 가능): closes·current_price → EntryResult
Evaluator = Callable[..., EntryResult]


def parse_watchlist(items: Iterable[str]) -> list[tuple[str, str]]:
    """"EXCD:SYMB" 문자열들을 (거래소, 종목) 튜플 목록으로. 빈/형식오류 항목은 무시."""
    out: list[tuple[str, str]] = []
    for item in items:
        item = (item or "").strip()
        if not item or ":" not in item:
            continue
        excd, _, symb = item.partition(":")
        excd, symb = excd.strip().upper(), symb.strip().upper()
        if excd and symb:
            out.append((excd, symb))
    return out


def resolve_watchlist_override(override_raw: str | None) -> list[tuple[str, str]]:
    """WATCHLIST_OVERRIDE(콤마 구분 "EXCD:SYMB")를 파싱. 미설정/빈값이면 빈 목록.

    검증 통제용: 값이 있으면 호출부(main)가 **DB 워치리스트를 무시하고** 이 목록만 쓴다.
    빈 목록이면 override 없음 → 기존 동작(DB 우선, 실패 시 폴백) 그대로. 평상시 영향 0.
    """
    return parse_watchlist((override_raw or "").split(","))


def format_entry_log(exchange: str, symbol: str, r: EntryResult) -> str:
    """EntryResult를 사람이 읽는 한 줄 로그로. (주문은 아직 연결 안 됨 — 표식 포함)"""
    if not r.evaluable:
        return f"{exchange}/{symbol} 판단불가(데이터 부족)"
    status = "진입신호 ✓" if r.enter else "대기"
    trend = "추세O" if r.trend.passed else "추세X"
    drop = r.pullback.drop_pct
    drop_s = f"눌림-{drop * 100:.1f}%" if drop is not None else "눌림-"
    rsi_v = r.rsi.value
    rsi_s = f"RSI{rsi_v:.0f}" if rsi_v is not None else "RSI-"
    bb = "볼린저O" if r.bollinger.signal else "볼린저-"
    macd = "MACD O" if r.macd.rebound else "MACD-"
    return (
        f"{exchange}/{symbol} {status} | {trend} {drop_s} "
        f"반등{r.rebound_count}/3 ({rsi_s}·{bb}·{macd}) (주문 미연결)"
    )


def _fetch_daily(client: Broker, exchange: str, symbol: str, daily_cache: Any) -> Any:
    """일봉 조회 — 캐시가 있으면 캐시 경유(TTL 내 KIS 호출 0), 없으면 직접 조회.

    daily_cache=None이면 기존 동작(매번 직접 조회) 그대로 — 캐시 미주입 시 영향 0.
    """
    if daily_cache is not None:
        return daily_cache.get(client, exchange, symbol)
    return client.get_overseas_daily_prices(exchange, symbol)


def poll_once(
    client: Broker,
    watchlist: list[tuple[str, str]],
    evaluator: Evaluator = evaluate_entry,
    recorder: Any = None,
    executor: Any = None,
    daily_cache: Any = None,
) -> None:
    """워치리스트를 한 바퀴 돌며 일봉+현재가로 진입 판단·로그. 한 종목 실패는 다음 종목/루프를 막지 않는다.

    recorder가 있으면 판단을 변화 시에만 기록. executor가 있으면 진입 신호 시 주문을 처리한다
    (executor가 드라이런/실주문 모드를 자체 판단 — 기본 드라이런, LIVE+paper일 때만 실주문).
    일봉은 daily_cache(주입 시) 경유로 캐싱하고, 현재가는 매 주기 실시간 조회한다.
    """
    for exchange, symbol in watchlist:
        try:
            daily = _fetch_daily(client, exchange, symbol, daily_cache)
            price = client.get_overseas_price(exchange, symbol).get("price")
            closes = [close for _date, close in daily]
            result = evaluator(closes, current_price=price)
            logger.info("%s", format_entry_log(exchange, symbol, result))
            if recorder is not None:
                recorder.record_if_changed(exchange, symbol, result)
            if result.enter and executor is not None:
                executor.handle(exchange, symbol, price, result)
        except Exception as exc:  # 일시적 에러·레이트리밋 등 — 죽지 말고 다음 종목/주기로
            logger.warning(
                "판단 실패 %s/%s: %s: %s — 다음 주기로 계속",
                exchange,
                symbol,
                type(exc).__name__,
                exc,
            )


def check_positions_once(
    client: Broker,
    positions: list[dict],
    executor: Any,
    evaluator: Evaluator = evaluate_entry,
    daily_cache: Any = None,
) -> None:
    """보유 포지션마다 손절·익절을 먼저 점검하고, 청산이 없으면 분할 2·3차 추가매수를 점검한다.

    순서(물타기 방지의 핵심): 손절 → 익절 → 추가매수. 청산이 트리거되면(드라이런 포함)
    그 주기엔 추가매수 점검을 하지 않는다. 한 주기 한 포지션당 한 액션만.
    분할 완료(tranche_stage≥3)·단계 미상 포지션은 일봉 조회 자체를 생략한다(API 절약).
    한 종목 실패는 다음 종목/루프를 막지 않는다.
    """
    for position in positions:
        symbol = position.get("symbol")
        try:
            order_excd = position.get("exchange") or ""
            price_excd = ORDER_TO_PRICE_EXCD.get(order_excd, order_excd)  # NASD→NAS
            price = client.get_overseas_price(price_excd, symbol).get("price")
            if executor.handle_position(position, price):  # 손절·익절 점검(한 번만 매도)
                continue  # 청산(시도) — 같은 주기 추가매수 없음(손절 우선)
            stage = position.get("tranche_stage")
            if stage is None or stage >= MAX_TRANCHE_STAGE:
                continue  # 분할 완료·단계 미상 — 추가매수 대상 아님
            daily = _fetch_daily(client, price_excd, symbol, daily_cache)
            closes = [close for _date, close in daily]
            entry = evaluator(closes, current_price=price)  # 반등 유지 재평가
            executor.handle_add_tranche(position, price, entry)
        except Exception as exc:  # 조회/판정 실패 — 죽지 말고 계속
            logger.warning("포지션 점검 실패 %s: %s: %s — 다음 주기로 계속", symbol, type(exc).__name__, exc)


def run_poll_loop(
    client: Broker,
    watchlist: list[tuple[str, str]],
    interval: float,
    should_run: Callable[[], bool],
    sleep: Callable[[float], None] = time.sleep,
    evaluator: Evaluator = evaluate_entry,
    recorder: Any = None,
    executor: Any = None,
    position_loader: Callable[[], list[dict]] | None = None,
    daily_cache: Any = None,
    market_is_open: Callable[[], bool] | None = None,
    idle_sleep: float = DEFAULT_IDLE_SLEEP,
    now: Callable[[], datetime] | None = None,
    idle_log_interval: float = DEFAULT_IDLE_LOG_INTERVAL,
) -> None:
    """should_run()이 True인 동안 polling. 매 주기마다 진입 판단 + (포지션 있으면) 손절 점검 후 대기.

    market_is_open이 주입되면 장중에만 폴링하고, 장외엔 폴링을 건너뛰고 idle_sleep 간격으로 대기한다
    (종료 신호에 빠르게 반응하도록 interval 조각으로 나눠 잠). market_is_open=None이면 항상 폴링
    (개발·검증용 우회 = 기존 동작). 장외 상태 로그는 idle_log_interval마다만(스팸 방지).
    should_run/sleep/evaluator/recorder/executor/position_loader/daily_cache/market_is_open/now를
    주입받아 테스트에서 제어할 수 있다. daily_cache 주입 시 일봉은 TTL 캐싱, 현재가는 매 주기 실시간.
    """
    clock = now or (lambda: datetime.now(timezone.utc))
    last_idle_log: datetime | None = None
    while should_run():
        if market_is_open is None or market_is_open():
            poll_once(client, watchlist, evaluator, recorder, executor, daily_cache)
            if executor is not None and position_loader is not None:
                check_positions_once(client, position_loader(), executor, evaluator, daily_cache)
            last_idle_log = None  # 장중으로 돌아오면 다음 장외 진입 시 즉시 로그
            sleep(interval)
        else:
            cur = clock()
            if last_idle_log is None or (cur - last_idle_log).total_seconds() >= idle_log_interval:
                hours = seconds_until_open(cur) / 3600
                logger.info("장외 대기 중 — 다음 개장까지 약 %.1f시간", hours)
                last_idle_log = cur
            _interruptible_sleep(idle_sleep, interval, should_run, sleep)
