"""시세 폴링 루프 + 시나리오1 진입 판단 (주문 없이 로그까지).

워치리스트 종목마다 일봉+현재가를 broker로 받아 evaluate_entry로 진입 신호를 판단하고
로그로 출력한다. **이번 슬라이스는 판단·로그까지 — 주문·분할매수·익절손절·DB는 다음.**

KIS 호출은 broker-client(KisClient)만 경유한다. 두뇌(indicators)는 순수 함수 그대로 재사용.
무한 루프는 engine에만 둔다(ARCHITECTURE).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Iterable, Protocol

from worker.indicators import EntryResult, evaluate_entry
from worker.orders import OrderConfig, decide_buy_order, format_order_decision

logger = logging.getLogger("kestrel.engine")


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


def poll_once(
    client: Broker,
    watchlist: list[tuple[str, str]],
    evaluator: Evaluator = evaluate_entry,
    recorder: Any = None,
    order_config: OrderConfig | None = None,
    held_symbols: set[str] | None = None,
) -> None:
    """워치리스트를 한 바퀴 돌며 일봉+현재가로 진입 판단·로그. 한 종목 실패는 다음 종목/루프를 막지 않는다.

    recorder가 있으면 판단을 변화 시에만 기록. order_config가 있으면 진입 신호 시 주문 결정을
    **드라이런으로 로그만** 한다(실제 주문은 넣지 않는다 — 다음 단계).
    """
    held = held_symbols if held_symbols is not None else set()
    for exchange, symbol in watchlist:
        try:
            daily = client.get_overseas_daily_prices(exchange, symbol)
            price = client.get_overseas_price(exchange, symbol).get("price")
            closes = [close for _date, close in daily]
            result = evaluator(closes, current_price=price)
            logger.info("%s", format_entry_log(exchange, symbol, result))
            if recorder is not None:
                recorder.record_if_changed(exchange, symbol, result)
            if result.enter and order_config is not None:
                decision = decide_buy_order(
                    exchange, symbol, price, held_symbols=held, config=order_config
                )
                logger.info("%s", format_order_decision(decision))  # 드라이런 — 실주문 없음
        except Exception as exc:  # 일시적 에러·레이트리밋 등 — 죽지 말고 다음 종목/주기로
            logger.warning(
                "판단 실패 %s/%s: %s: %s — 다음 주기로 계속",
                exchange,
                symbol,
                type(exc).__name__,
                exc,
            )


def run_poll_loop(
    client: Broker,
    watchlist: list[tuple[str, str]],
    interval: float,
    should_run: Callable[[], bool],
    sleep: Callable[[float], None] = time.sleep,
    evaluator: Evaluator = evaluate_entry,
    recorder: Any = None,
    order_config: OrderConfig | None = None,
    held_symbols: set[str] | None = None,
) -> None:
    """should_run()이 True인 동안 polling. 매 주기마다 한 바퀴 판단 후 interval 만큼 대기.

    should_run/sleep/evaluator/recorder/order_config를 주입받아 테스트에서 제어할 수 있다.
    실서비스: should_run=lambda: <SIGTERM 플래그>, sleep=time.sleep, evaluator=evaluate_entry.
    """
    while should_run():
        poll_once(client, watchlist, evaluator, recorder, order_config, held_symbols)
        sleep(interval)
