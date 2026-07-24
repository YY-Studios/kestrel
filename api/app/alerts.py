"""알림 피드 — signal_log(선별) + orders(전건)를 시간순으로 병합해 "무슨 일이 있었나"를 보여준다.

api는 Supabase를 service 키로 서버에서 읽는다(프론트 키 노출 금지 — CLAUDE.md). 두 계층:
  - 순수 조합(order_to_alert·select_signal_alerts·build_alerts) — 테스트로 고정.
  - 얇은 조회(_fetch_orders·_fetch_signals) + 라우터(GET /api/alerts).

**선별이 핵심** — signal_log를 전부 알림으로 만들면 시끄럽다. 의미 있는 사건만 채택한다:
  - 진입 신호(decision=enter): "매수 신호 발생" (중요).
  - 추세 전환(trend_ok가 직전 관측 대비 통과↔이탈): "추세 통과"/"추세 이탈" (낮은 중요도).
  - 그 외(반등 개수만 변함·단순 대기·판단불가)는 제외.
orders는 전건이 사건(체결)이므로 모두 알림으로.

severity(색 힌트) — UI_GUIDE 준수:
  positive(익절 이익)=초록 · negative(손절 손실)=빨강 · fill(매수 체결)=파랑(상태) ·
  fail(주문 실패)=주황(상태) · signal(진입 신호)=노랑(신호) · info(추세 변화)=중립.
등락 초록·빨강은 실현손익(익절/손절)에만 쓰고, 체결·신호는 상태색을 쓴다.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.supabase_client import get_supabase

logger = logging.getLogger("kestrel.api")

ORDERS_TABLE = "orders"
SIGNAL_LOG_TABLE = "signal_log"
DEFAULT_LIMIT = 50

# 매수 차수/청산 유형 → 체결 알림 제목.
_ORDER_TITLES = {
    "buy_1": "1차 매수 체결", "buy_2": "2차 매수 체결", "buy_3": "3차 매수 체결",
    "sell_tp": "익절 체결", "sell_sl": "손절 체결",
}

router = APIRouter()


def order_to_alert(row: dict) -> dict:
    """orders 한 건 → 체결 알림. 매도의 realized_pnl 부호로 초록/빨강, 매수는 파랑(체결)."""
    side = (row.get("side") or "").strip().lower()
    order_type = row.get("order_type") or ""
    status = row.get("status")
    symbol = (row.get("symbol") or "").strip().upper()
    is_sell = side == "sell"
    pnl = row.get("realized_pnl") if is_sell else None

    title = _ORDER_TITLES.get(order_type) or ("매도 체결" if is_sell else "매수 체결")

    if status == "rejected":
        severity = "fail"
        title = f"{title} 실패"
    elif is_sell:
        severity = "positive" if (pnl is not None and pnl >= 0) else "negative"
    else:
        severity = "fill"

    price = row.get("price")
    qty = row.get("quantity")
    parts: list[str] = []
    if price is not None:
        parts.append(f"${price}")
    if qty is not None:
        parts.append(f"{qty}주")
    if pnl is not None:
        parts.append(f"{'+' if pnl >= 0 else ''}${round(pnl, 2)}")
    detail = " · ".join(parts)

    return {
        "kind": "order",
        "type": order_type or side,
        "symbol": symbol,
        "title": title,
        "detail": detail,
        "severity": severity,
        "realized_pnl": pnl,
        "created_at": row.get("created_at"),
    }


def _signal_alert(row: dict, subtype: str) -> dict:
    symbol = (row.get("symbol") or "").strip().upper()
    if subtype == "enter":
        rc, rr = row.get("rebound_count"), row.get("rebound_required")
        rsi = row.get("rsi")
        detail = f"반등 {rc}/{rr}" if rc is not None and rr is not None else "진입 신호"
        if rsi is not None:
            detail += f" · RSI {round(rsi)}"
        title, severity = "매수 신호 발생", "signal"
    elif subtype == "trend_pass":
        title, detail, severity = "추세 통과", "20일선 > 60일선", "info"
    else:  # trend_break
        title, detail, severity = "추세 이탈", "20일선 < 60일선", "info"
    return {
        "kind": "signal",
        "type": subtype,
        "symbol": symbol,
        "title": title,
        "detail": detail,
        "severity": severity,
        "realized_pnl": None,
        "created_at": row.get("created_at"),
    }


def select_signal_alerts(signal_rows: list[dict]) -> list[dict]:
    """signal_log에서 의미 있는 사건만 선별: 진입 신호(enter) + 추세 전환.

    오래된→최신 순으로 훑으며 종목별 직전 trend_ok를 추적한다. 진입은 그 자체로 알림,
    나머지 행은 추세가 직전 관측과 달라졌을 때만 알림(반등 개수만 바뀐 자잘한 변화는 제외).
    """
    rows = sorted(signal_rows, key=lambda r: r.get("created_at") or "")
    prev_trend: dict[str, Any] = {}
    _MISSING = object()
    alerts: list[dict] = []
    for r in rows:
        symbol = (r.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        trend = r.get("trend_ok")
        if r.get("decision") == "enter":
            alerts.append(_signal_alert(r, "enter"))
        else:
            before = prev_trend.get(symbol, _MISSING)
            if before is not _MISSING and before is not None and trend is not None and trend != before:
                alerts.append(_signal_alert(r, "trend_pass" if trend else "trend_break"))
        prev_trend[symbol] = trend
    return alerts


def build_alerts(orders: list[dict], signal_rows: list[dict], limit: int) -> dict:
    """orders(전건) + 선별된 signal 알림을 최신순 병합 후 limit 적용."""
    items = [order_to_alert(o) for o in orders if (o.get("symbol") or "").strip()]
    items += select_signal_alerts(signal_rows)
    items.sort(key=lambda a: a.get("created_at") or "", reverse=True)
    items = items[:limit]
    return {"count": len(items), "items": items}


def _fetch_orders(client: Any, limit: int = DEFAULT_LIMIT) -> list[dict]:
    resp = client.table(ORDERS_TABLE).select("*").order("created_at", desc=True).limit(limit).execute()
    return list(getattr(resp, "data", None) or [])


def _fetch_signals(client: Any, limit: int = 300) -> list[dict]:
    # 선별로 크게 줄어들므로 넉넉히 읽되(추세 전환 판정에 연속성 필요), 병합 후 limit로 자른다.
    resp = client.table(SIGNAL_LOG_TABLE).select("*").order("created_at", desc=True).limit(limit).execute()
    return list(getattr(resp, "data", None) or [])


@router.get("/api/alerts")
def get_alerts_endpoint() -> dict:
    """알림 피드(선별된 signal + 체결, 최신순). DB 실패 시 500(내부 상세는 로그에만)."""
    try:
        client = get_supabase()
        orders = _fetch_orders(client)
        signals = _fetch_signals(client)
    except Exception as exc:
        logger.warning("알림 조회 실패: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="알림을 불러오지 못했습니다") from exc
    return build_alerts(orders, signals, DEFAULT_LIMIT)
