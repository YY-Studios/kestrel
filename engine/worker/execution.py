"""실주문 실행 (진입 1차 매수) — 최고 신중도.

진입 결정(OrderDecision, 발주 대상)을 실제 주문으로 연결한다. 단:
  - **기본은 드라이런**(로그만). LIVE_ORDERS=true AND paper(is_paper)일 때만 실주문.
  - real(is_paper=False)이면 LIVE여도 실주문하지 않는다(broker도 이중 차단).
  - 중복 방지: 이미 보유(held) 또는 이번 세션에서 이미 발주한 종목은 재발주 금지.
  - 거래소 코드는 시세(NAS/NYS/AMS) → 주문(NASD/NYSE/AMEX)으로 매핑해 호출.
  - **주문 성공 후에만** orders/positions 기록. 기록 실패는 경고만(주문은 이미 나감 — 루프 안 죽임).

분할 2·3차·익절·손절은 다음 단계. KIS 호출은 broker(KisClient)만 경유한다.
"""

from __future__ import annotations

import logging
from typing import Any

from worker.db import insert_order, upsert_position
from worker.indicators import EntryResult
from worker.orders import OrderConfig, OrderDecision, decide_buy_order, format_order_decision

logger = logging.getLogger("kestrel.engine")

# 시세 거래소 코드 → 주문 거래소 코드.
_PRICE_TO_ORDER_EXCD = {"NAS": "NASD", "NYS": "NYSE", "AMS": "AMEX"}


class OrderExecutor:
    def __init__(
        self,
        broker: Any,
        db_client: Any,
        config: OrderConfig,
        *,
        live: bool,
        is_paper: bool,
        held_symbols: set[str],
        target_pct: float = 0.08,
        stop_pct: float = 0.05,
    ) -> None:
        self._broker = broker
        self._db = db_client
        self._config = config
        self._live = live
        self._is_paper = is_paper
        self._held = set(held_symbols)
        self._placed: set[str] = set()  # 이번 세션에 발주한 종목(중복 방지)
        self._target_pct = target_pct
        self._stop_pct = stop_pct

    @property
    def mode(self) -> str:
        return "LIVE" if (self._live and self._is_paper) else "DRYRUN"

    def handle(self, exchange: str, symbol: str, current_price: float | None, entry: EntryResult) -> None:
        """진입 신호 종목 처리: 결정 → (드라이런 로그 | 실주문+기록)."""
        decision = decide_buy_order(
            exchange, symbol, current_price, held_symbols=self._held, config=self._config
        )
        if not decision.ordered:
            logger.info("%s", format_order_decision(decision))  # 생략 사유 로그
            return
        if symbol in self._placed:
            logger.info("주문 스킵: %s 이번 세션에 이미 발주함(중복 방지)", symbol)
            return

        # LIVE + paper 가 아니면 드라이런(실주문 없음).
        if not (self._live and self._is_paper):
            logger.info("%s", format_order_decision(decision))
            return

        order_excd = _PRICE_TO_ORDER_EXCD.get(exchange, exchange)  # NAS→NASD
        try:
            result = self._broker.place_overseas_order(
                order_excd, symbol, decision.quantity, "buy", decision.limit_price
            )
        except Exception as exc:  # rt_cd≠0 등 — 루프는 계속
            logger.warning("실주문 실패 %s/%s: %s — 루프 계속", order_excd, symbol, exc)
            self._safe_record_order(order_excd, symbol, decision, None, entry, status="rejected")
            return

        order_no = (result or {}).get("order_no")
        logger.info(
            "실주문 전송(LIVE): %s/%s %d주 매수 지정가 ~$%s ODNO=%s",
            order_excd, symbol, decision.quantity, decision.limit_price, order_no,
        )
        self._placed.add(symbol)
        self._held.add(symbol)
        self._record_fill(order_excd, symbol, decision, order_no, entry)

    # --- 기록(주문 성공 후) — 실패해도 루프 안 죽임 -------------------------
    def _reason(self, entry: EntryResult) -> str:
        return f"진입: 추세{'O' if entry.trend.passed else 'X'} 반등{entry.rebound_count}/{entry.rebound_required}"

    def _safe_record_order(self, exchange, symbol, decision, order_no, entry, *, status) -> None:
        if self._db is None:
            logger.warning("DB 없음 — 주문 기록 생략 (ODNO=%s)", order_no)
            return
        record = {
            "exchange": exchange, "symbol": symbol, "side": "buy",
            "quantity": decision.quantity, "price": decision.limit_price,
            "order_type": "buy_1", "broker_order_id": order_no, "status": status,
            "reason": self._reason(entry),
        }
        try:
            insert_order(self._db, record)
        except Exception as exc:
            logger.warning("orders 기록 실패 (ODNO=%s): %s — 계속", order_no, type(exc).__name__)

    def _record_fill(self, exchange, symbol, decision, order_no, entry) -> None:
        self._safe_record_order(exchange, symbol, decision, order_no, entry, status="submitted")
        if self._db is None:
            return
        price = decision.limit_price or 0.0
        position = {
            "exchange": exchange, "symbol": symbol,
            "avg_price": price, "quantity": decision.quantity, "tranche_stage": 1,
            "target_price": price * (1 + self._target_pct),
            "stop_price": price * (1 - self._stop_pct),
            "status": "open", "entry_reason": self._reason(entry),
        }
        try:
            upsert_position(self._db, position)
        except Exception as exc:
            logger.warning("positions 기록 실패 (ODNO=%s): %s — 계속", order_no, type(exc).__name__)
