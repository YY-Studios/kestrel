"""시세 폴링 루프 (engine 첫 슬라이스).

워치리스트 종목의 현재가를 주기적으로 조회해 로그로 출력한다.
지표·신호 판단·주문·DB는 다음 슬라이스. 이번 슬라이스의 목적은 상시 루프의 뼈대
(broker 연동·주기·실패 내성·종료 처리)를 단순한 상태에서 검증하는 것.

KIS 호출은 broker-client(KisClient)만 경유한다. 무한 루프는 engine에만 둔다(ARCHITECTURE).
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Iterable, Protocol

logger = logging.getLogger("kestrel.engine")


class PriceSource(Protocol):
    """루프가 필요로 하는 broker의 최소 인터페이스(테스트는 가짜로 대체)."""

    def get_overseas_price(self, exchange: str, symbol: str) -> dict: ...


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


def poll_once(client: PriceSource, watchlist: list[tuple[str, str]]) -> None:
    """워치리스트를 한 바퀴 돌며 시세를 조회·로그. 한 종목 실패가 다음 종목/루프를 막지 않는다."""
    for exchange, symbol in watchlist:
        try:
            result = client.get_overseas_price(exchange, symbol)
            logger.info("시세 %s/%s · 현재가=%s", exchange, symbol, result.get("price"))
        except Exception as exc:  # 일시적 에러·레이트리밋 등 — 죽지 말고 다음 주기로
            logger.warning(
                "시세 조회 실패 %s/%s: %s: %s — 다음 주기로 계속",
                exchange,
                symbol,
                type(exc).__name__,
                exc,
            )


def run_poll_loop(
    client: PriceSource,
    watchlist: list[tuple[str, str]],
    interval: float,
    should_run: Callable[[], bool],
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """should_run()이 True인 동안 polling. 매 주기마다 한 바퀴 조회 후 interval 만큼 대기.

    should_run/sleep을 주입받아 테스트에서 "몇 회 돌고 멈추게" 할 수 있다.
    실서비스에선 should_run=lambda: <SIGTERM 플래그>, sleep=time.sleep.
    """
    while should_run():
        poll_once(client, watchlist)
        sleep(interval)
