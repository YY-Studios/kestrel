"""포지션 조회 — Supabase positions(status=open) + 종목별 현재가(KIS) 조합.

api는 Supabase를 service 키로 서버에서 읽고(프론트 키 노출 금지), 현재가는 broker-client로
조회한다(증권사 직접 호출 금지 — CLAUDE.md). 두 계층으로 나눈다:
  - 순수 조합(build_position_item·build_positions_response) — 테스트로 고정.
  - 얇은 조회(_fetch_open_positions·_load_prices) + 라우터(GET /api/positions).

현재가/손익은 broker 조회에 의존한다. 조회 실패 종목은 current_price=null로 내려보내고
손익·거리도 null — 가짜 숫자를 채우지 않는다(화면은 평단·수량 등 DB값으로 안 깨진다).
positions엔 거래소가 주문코드(NASD)로 저장되므로 시세 조회 전 시세코드(NAS)로 매핑한다.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.broker_client import get_broker
from app.config import get_settings
from app.supabase_client import get_supabase

logger = logging.getLogger("kestrel.api")

POSITIONS_TABLE = "positions"
MAX_POSITIONS = 3

# 주문 거래소코드(positions 저장값) → 시세 거래소코드(현재가 조회용).
_ORDER_TO_PRICE_EXCD = {"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS"}

router = APIRouter()


def to_price_exchange(order_excd: str) -> str:
    """주문코드(NASD)를 시세코드(NAS)로. 이미 시세코드거나 미지의 값이면 그대로 둔다."""
    return _ORDER_TO_PRICE_EXCD.get((order_excd or "").upper(), (order_excd or "").upper())


def build_position_item(pos: dict, current_price: float | None) -> dict:
    """포지션 1건 + 현재가를 화면용 dict로. 현재가 없으면 손익·거리는 null(DB값은 유지).

    - unrealized_pnl = (현재가 - 평단) × 수량
    - unrealized_pnl_pct = (현재가 - 평단) / 평단 × 100
    - target_distance_pct = (목표가 - 현재가) / 현재가 × 100  (현재가에서 목표까지, +)
    - stop_distance_pct = (손절가 - 현재가) / 현재가 × 100    (현재가에서 손절까지, −)
    """
    avg = pos.get("avg_price")
    qty = pos.get("quantity")
    target = pos.get("target_price")
    stop = pos.get("stop_price")

    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    target_distance_pct: float | None = None
    stop_distance_pct: float | None = None

    if current_price is not None and avg not in (None, 0):
        unrealized_pnl_pct = (current_price - avg) / avg * 100
        if qty is not None:
            unrealized_pnl = (current_price - avg) * qty
    if current_price not in (None, 0):
        if target is not None:
            target_distance_pct = (target - current_price) / current_price * 100
        if stop is not None:
            stop_distance_pct = (stop - current_price) / current_price * 100

    return {
        "symbol": (pos.get("symbol") or "").strip().upper(),
        "exchange": (pos.get("exchange") or "").strip().upper(),
        "avg_price": avg,
        "quantity": qty,
        "tranche_stage": pos.get("tranche_stage"),
        "target_price": target,
        "stop_price": stop,
        "current_price": current_price,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "target_distance_pct": target_distance_pct,
        "stop_distance_pct": stop_distance_pct,
        "entry_reason": pos.get("entry_reason"),
        "opened_at": pos.get("created_at") or pos.get("opened_at"),
    }


def build_positions_response(
    positions: list[dict], prices: dict[str, float | None], max_positions: int
) -> dict:
    """open 포지션 목록 + 종목별 현재가(prices)를 화면용 응답으로 조합한다."""
    items = [
        build_position_item(p, prices.get((p.get("symbol") or "").strip().upper()))
        for p in positions
        if (p.get("symbol") or "").strip()
    ]
    return {"held": len(items), "limit": max_positions, "items": items}


def _fetch_open_positions(client: Any) -> list[dict]:
    resp = client.table(POSITIONS_TABLE).select("*").eq("status", "open").execute()
    return list(getattr(resp, "data", None) or [])


def _load_prices(positions: list[dict]) -> dict[str, float | None]:
    """종목별 현재가를 broker로 조회. 종목·broker 실패는 해당 종목 None으로(대시보드 폴백과 동일).

    positions의 exchange(NASD)를 시세코드(NAS)로 매핑해 조회한다. 실네트워크는 이 함수에만 있다.
    """
    prices: dict[str, float | None] = {}
    if not positions:
        return prices
    broker = None
    try:
        broker = get_broker()
        for pos in positions:
            symbol = (pos.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            price_excd = to_price_exchange(pos.get("exchange") or "")
            try:
                quote = broker.get_overseas_price(price_excd, symbol)
                prices[symbol] = quote.get("price")
            except Exception as exc:  # 종목 하나 실패가 나머지를 막지 않는다
                logger.warning("현재가 조회 실패 %s: %s — null 폴백", symbol, type(exc).__name__)
                prices[symbol] = None
    except Exception as exc:  # broker 생성 자체 실패 — 전부 null 폴백(화면은 DB값으로 유지)
        logger.warning("broker 사용 불가(포지션 현재가): %s — 전부 null", type(exc).__name__)
    finally:
        if broker is not None:
            try:
                broker.close()
            except Exception:
                pass
    return prices


@router.get("/api/positions")
def get_positions_endpoint() -> dict:
    """보유 포지션 현황(현재가·손익 포함). DB 실패 시 500(내부 상세는 로그에만)."""
    try:
        positions = _fetch_open_positions(get_supabase())
        prices = _load_prices(positions)  # 실패해도 종목별 None 폴백 — 화면 유지
        resp = build_positions_response(positions, prices, MAX_POSITIONS)
        resp["is_paper"] = get_settings().kis_is_paper  # UI paper/real 표기용
        return resp
    except Exception as exc:
        logger.warning("포지션 조회 실패: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="포지션을 불러오지 못했습니다") from exc
