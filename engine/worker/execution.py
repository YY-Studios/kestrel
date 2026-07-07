"""실주문 실행 (진입 1차 + 분할 2·3차 매수 + 손절·익절 매도) — 최고 신중도.

주문 결정(orders의 판정)을 실제 주문으로 연결한다. 단:
  - **기본은 드라이런**(로그만). LIVE_ORDERS=true AND paper(is_paper)일 때만 실주문.
  - real(is_paper=False)이면 LIVE여도 실주문하지 않는다(broker도 이중 차단).
  - 중복 방지: 이미 보유(held)·이번 세션에 발주한 종목/차수는 재발주 금지.
  - 거래소 코드는 시세(NAS/NYS/AMS) → 주문(NASD/NYSE/AMEX)으로 매핑해 호출.
  - **주문 성공 후에만** orders/positions 기록. 기록 실패는 경고만(주문은 이미 나감 — 루프 안 죽임).
  - 분할 2·3차 갱신 정책: 평단은 가중평균 재계산, **손절가는 1차 값 유지**
    (새 평단 기준으로 낮추면 손절선을 밀어내리는 물타기가 된다 — ROADMAP),
    목표가는 "평단 대비 +target_pct" 의미를 유지하도록 새 평단 기준 재계산.

KIS 호출은 broker(KisClient)만 경유한다.
"""

from __future__ import annotations

import logging
from typing import Any

from worker.db import close_position, insert_order, upsert_position
from worker.indicators import EntryResult
from worker.orders import (
    AddTrancheDecision,
    OrderConfig,
    OrderDecision,
    decide_add_tranche,
    decide_buy_order,
    decide_stop_loss,
    decide_take_profit,
    format_order_decision,
    merge_tranche_fill,
)

logger = logging.getLogger("kestrel.engine")

# 시세 거래소 코드 → 주문 거래소 코드 (그리고 역방향).
_PRICE_TO_ORDER_EXCD = {"NAS": "NASD", "NYS": "NYSE", "AMS": "AMEX"}
ORDER_TO_PRICE_EXCD = {v: k for k, v in _PRICE_TO_ORDER_EXCD.items()}


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

    # --- 청산(손절/익절) 매도 --------------------------------------------
    def handle_position(self, position: dict, current_price: float | None) -> bool:
        """한 포지션의 청산 점검: 손절 먼저, 아니면 익절. 한 주기에 **한 번만** 매도한다.

        청산을 시도했으면(드라이런 포함) True — 호출부는 True면 이 주기에 추가매수를
        점검하지 않는다(청산 우선, 손절선 도달 시 추가매수 금지 원칙의 집행 지점).
        """
        if self.handle_stop_loss(position, current_price):
            return True
        return self.handle_take_profit(position, current_price)

    def handle_stop_loss(self, position: dict, current_price: float | None) -> bool:
        """손절 판정 → 조건 시 매도. 손절은 '항상 실행'(홀딩/물타기 금지). 매도 시도 여부를 반환."""
        decision = decide_stop_loss(position, current_price)
        if not decision.should_sell:
            return False
        self._sell(position, current_price, decision, "sell_sl", "손절")
        return True

    def handle_take_profit(self, position: dict, current_price: float | None) -> bool:
        """익절 판정 → 목표가 도달 시 전량 매도. 매도 시도 여부를 반환."""
        decision = decide_take_profit(position, current_price)
        if not decision.should_sell:
            return False
        self._sell(position, current_price, decision, "sell_tp", "익절")
        return True

    # --- 분할 2·3차 매수 --------------------------------------------------
    def handle_add_tranche(
        self, position: dict, current_price: float | None, entry: EntryResult | None
    ) -> None:
        """분할 2·3차 매수 처리: 판정 → (드라이런 로그 | 실주문+포지션 갱신).

        손절선 이하·반등 소멸·분할 완료는 decide_add_tranche가 차단한다.
        호출부(loop)는 청산이 없었던 포지션에만 이걸 부른다(청산 우선).
        """
        decision = decide_add_tranche(position, current_price, entry, config=self._config)
        symbol = decision.symbol
        if not decision.ordered:
            logger.info("추가매수 안 함: %s — %s (드라이런/판정)", symbol, decision.reason)
            return

        key = f"add:{symbol}:{decision.tranche_stage}"
        if key in self._placed:  # DB 기록 실패 등으로 stage가 안 올라도 같은 차수 재발주 금지
            logger.info("추가매수 스킵: %s %d차 이번 세션에 이미 발주함(중복 방지)", symbol, decision.tranche_stage)
            return

        if not (self._live and self._is_paper):  # real이면 LIVE여도 차단
            logger.info(
                "%d차 매수 예정(드라이런): %s %d주 지정가 ~$%s (%.0f%%) — 실제 주문 안 나감",
                decision.tranche_stage, symbol, decision.quantity,
                decision.limit_price, decision.tranche_pct * 100,
            )
            return

        order_excd = position.get("exchange") or ""  # 포지션은 주문 코드(NASD)를 저장
        try:
            result = self._broker.place_overseas_order(
                order_excd, symbol, decision.quantity, "buy", decision.limit_price
            )
        except Exception as exc:  # rt_cd≠0 등 — 루프는 계속
            logger.warning(
                "추가매수 실주문 실패 %s/%s %d차: %s — 루프 계속",
                order_excd, symbol, decision.tranche_stage, exc,
            )
            self._record_add_order(order_excd, symbol, decision, None, status="rejected")
            return

        order_no = (result or {}).get("order_no")
        logger.info(
            "추가매수 전송(LIVE): %s/%s %d차 %d주 지정가 ~$%s ODNO=%s",
            order_excd, symbol, decision.tranche_stage, decision.quantity,
            decision.limit_price, order_no,
        )
        self._placed.add(key)
        self._record_add_fill(order_excd, symbol, position, decision, order_no)

    def _record_add_order(self, exchange, symbol, decision: AddTrancheDecision, order_no, *, status) -> None:
        if self._db is None:
            logger.warning("DB 없음 — 추가매수 기록 생략 (ODNO=%s)", order_no)
            return
        record = {
            "exchange": exchange, "symbol": symbol, "side": "buy",
            "quantity": decision.quantity, "price": decision.limit_price,
            "order_type": f"buy_{decision.tranche_stage}", "broker_order_id": order_no,
            "status": status, "reason": decision.reason,
        }
        try:
            insert_order(self._db, record)
        except Exception as exc:
            logger.warning("orders(추가매수) 기록 실패 (ODNO=%s): %s — 계속", order_no, type(exc).__name__)

    def _record_add_fill(self, exchange, symbol, position, decision: AddTrancheDecision, order_no) -> None:
        self._record_add_order(exchange, symbol, decision, order_no, status="submitted")
        if self._db is None:
            return
        fill_price = decision.limit_price or 0.0
        new_avg, total_qty = merge_tranche_fill(
            float(position["avg_price"]), int(position["quantity"]), fill_price, decision.quantity
        )
        updated = {
            "exchange": exchange, "symbol": symbol,
            "avg_price": new_avg, "quantity": total_qty, "tranche_stage": decision.tranche_stage,
            # 손절가는 1차 값 유지(낮추면 물타기), 목표가는 새 평단 기준 재계산(모듈 docstring 참고).
            "target_price": new_avg * (1 + self._target_pct),
            "stop_price": position["stop_price"],
            "status": "open",
        }
        try:
            upsert_position(self._db, updated)
        except Exception as exc:
            logger.warning("positions(추가매수) 기록 실패 (ODNO=%s): %s — 계속", order_no, type(exc).__name__)

    def _sell(self, position, current_price, decision, order_type, label) -> None:
        """손절·익절 공통 매도 실행: 드라이런/LIVE 분기·중복방지·real차단·성공 후 기록."""
        symbol = position["symbol"]
        key = f"sell:{symbol}"
        if key in self._placed:  # 중복 매도 방지(같은 주기 손절·익절 동시 방어 포함)
            return
        if not (self._live and self._is_paper):  # real이면 LIVE여도 차단
            logger.info(
                "%s 예정(드라이런): %s @ %s (손익 %s) — 실제 매도 안 나감",
                label, symbol, current_price, decision.realized_pnl,
            )
            return

        order_excd = position.get("exchange") or ""  # 포지션은 주문 코드(NASD)를 저장
        qty = int(position["quantity"])
        try:
            result = self._broker.place_overseas_order(order_excd, symbol, qty, "sell", current_price)
        except Exception as exc:  # 매도 실패는 특히 명확히 — 다음 주기 재시도 대상, 포지션 유지
            logger.warning("%s 매도 실패 %s/%s: %s — 재시도 대상, 루프 계속", label, order_excd, symbol, exc)
            return

        order_no = (result or {}).get("order_no")
        logger.info(
            "%s 매도 전송(LIVE): %s/%s %d주 @ $%s ODNO=%s 손익 %s",
            label, order_excd, symbol, qty, current_price, order_no, decision.realized_pnl,
        )
        self._placed.add(key)
        self._held.discard(symbol)
        self._record_sell(order_excd, symbol, qty, current_price, order_no, decision, order_type, f"{label} — {decision.reason}")

    def _record_sell(self, exchange, symbol, qty, price, order_no, decision, order_type, reason) -> None:
        if self._db is None:
            logger.warning("DB 없음 — 매도 기록 생략 (ODNO=%s)", order_no)
            return
        order = {
            "exchange": exchange, "symbol": symbol, "side": "sell", "quantity": qty, "price": price,
            "order_type": order_type, "broker_order_id": order_no, "status": "submitted",
            "realized_pnl": decision.realized_pnl, "reason": reason,
        }
        try:
            insert_order(self._db, order)
        except Exception as exc:
            logger.warning("orders(매도) 기록 실패 (ODNO=%s): %s — 계속", order_no, type(exc).__name__)
        try:
            close_position(self._db, symbol)
        except Exception as exc:
            logger.warning("positions 청산 기록 실패 (ODNO=%s): %s — 계속", order_no, type(exc).__name__)

    # --- 기록(매수 성공 후) — 실패해도 루프 안 죽임 -------------------------
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
