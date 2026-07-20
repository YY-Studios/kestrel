"""매매내역 조회 — Supabase orders(체결 기록, 누적)를 시간순으로.

api는 Supabase를 service 키로 서버에서 읽는다(프론트 키 노출 금지 — CLAUDE.md). 두 계층:
  - 순수 조합(build_order_item·build_orders_response) — 테스트로 고정.
  - 얇은 조회(_fetch_orders) + 라우터(GET /api/orders).

orders는 engine이 남긴 개별 체결(매수 1·2·3차 / 매도 익절·손절). 실현손익(realized_pnl)은
매도 기록에만 있다 — 매수엔 null(가짜 손익 금지). 현재가는 필요 없다(과거 체결 기록).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.supabase_client import get_supabase

logger = logging.getLogger("kestrel.api")

ORDERS_TABLE = "orders"
DEFAULT_LIMIT = 50

# order_type → 화면 라벨. 매수는 분할 차수, 매도는 청산 유형.
_DETAIL_LABELS = {
    "buy_1": "1차", "buy_2": "2차", "buy_3": "3차",
    "sell_tp": "익절", "sell_sl": "손절",
}
# 매도 청산 유형(뱃지 색 구분용): 익절(tp)·손절(sl).
_LIQUIDATION = {"sell_tp": "tp", "sell_sl": "sl"}

router = APIRouter()


def detail_label(order_type: str | None) -> str:
    """order_type을 화면 라벨로. 매수=차수(1·2·3차), 매도=청산유형(익절·손절). 미지값은 빈 문자열."""
    return _DETAIL_LABELS.get(order_type or "", "")


def build_order_item(row: dict) -> dict:
    """orders 한 행을 화면용 dict로. realized_pnl은 매도(side=sell)에만 싣는다(매수는 null)."""
    side = (row.get("side") or "").strip().lower()
    order_type = row.get("order_type") or ""
    is_sell = side == "sell"
    return {
        "symbol": (row.get("symbol") or "").strip().upper(),
        "exchange": (row.get("exchange") or "").strip().upper(),
        "side": side,
        "order_type": order_type,
        "kind_label": "매수" if side == "buy" else "매도" if side == "sell" else "",
        "detail_label": detail_label(order_type),
        "liquidation": _LIQUIDATION.get(order_type) if is_sell else None,
        "quantity": row.get("quantity"),
        "price": row.get("price"),
        "broker_order_id": row.get("broker_order_id"),
        "status": row.get("status"),
        "realized_pnl": row.get("realized_pnl") if is_sell else None,  # 매수엔 실현손익 없음
        "reason": row.get("reason"),
        "created_at": row.get("created_at"),
    }


def build_orders_response(rows: list[dict]) -> dict:
    """orders 행들을 최신순(created_at 내림차순)으로 정렬해 화면용 응답으로."""
    items = [build_order_item(r) for r in rows if (r.get("symbol") or "").strip()]
    items.sort(key=lambda it: it.get("created_at") or "", reverse=True)
    return {"count": len(items), "items": items}


def _fetch_orders(client: Any, limit: int = DEFAULT_LIMIT) -> list[dict]:
    resp = (
        client.table(ORDERS_TABLE)
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(getattr(resp, "data", None) or [])


@router.get("/api/orders")
def get_orders_endpoint() -> dict:
    """매매내역(최근 체결, 최신순). DB 실패 시 500(내부 상세는 로그에만)."""
    try:
        rows = _fetch_orders(get_supabase())
    except Exception as exc:
        logger.warning("매매내역 조회 실패: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="매매내역을 불러오지 못했습니다") from exc
    return build_orders_response(rows)
