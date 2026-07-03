"""대시보드 요약 — Supabase positions + watchlist/signal_log 조합.

실데이터만 노출한다. broker 미연결(예수금·평가자산)·미구현(지수·환율·경제일정)은
available=False 플래그로 구분하고 가짜 숫자를 채우지 않는다.

조합 구조:
  positions: Supabase positions(status=open) — 현재가/PnL은 broker 미연결로 null
  watchlist_summary: watchlist + signal_log 최신 1건 집계
  account: available=False (KIS 잔고 조회 미구현)
  market: available=False (지수·환율 미구현)
  calendar: available=False (경제일정 미구현)
  strategy: is_paper 여부 + watchlist 종목 수
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.supabase_client import get_supabase
from app.watchlist import build_watchlist_rows, fetch_watchlist_rows, latest_signal_by_symbol

logger = logging.getLogger("kestrel.api")

POSITIONS_TABLE = "positions"
WATCHLIST_TABLE = "watchlist"
SIGNAL_LOG_TABLE = "signal_log"
MAX_POSITIONS = 3

router = APIRouter()


def build_positions_summary(positions: list[dict], max_positions: int) -> dict:
    """open 포지션을 화면용 요약으로. 현재가/PnL은 broker 미연결이라 null."""
    items = [
        {
            "symbol": (p.get("symbol") or "").strip().upper(),
            "exchange": (p.get("exchange") or "").strip().upper(),
            "avg_price": p.get("avg_price"),
            "quantity": p.get("quantity"),
            "tranche_stage": p.get("tranche_stage"),
            "target_price": p.get("target_price"),
            "stop_price": p.get("stop_price"),
            "current_price": None,   # broker 미연결 — 준비 중
            "pnl_pct": None,         # broker 미연결 — 준비 중
        }
        for p in positions
        if (p.get("symbol") or "").strip()
    ]
    return {"available": True, "held": len(items), "limit": max_positions, "items": items}


def build_watchlist_summary(wl_rows: list[dict]) -> dict:
    """워치리스트 행들을 집계(추세 통과 수·신호 임박·진입 신호)."""
    trend_pass = sum(1 for r in wl_rows if r.get("trend_ok") is True)
    near_signal = sum(
        1 for r in wl_rows
        if r.get("trend_ok") is True and (r.get("rebound_count") or 0) >= 2
    )
    enter_count = sum(1 for r in wl_rows if r.get("decision") == "enter")
    return {
        "available": True,
        "total": len(wl_rows),
        "trend_pass": trend_pass,
        "near_signal": near_signal,
        "enter_count": enter_count,
    }


def _fetch_positions(client: Any) -> list[dict]:
    resp = (
        client.table(POSITIONS_TABLE)
        .select("*")
        .eq("status", "open")
        .execute()
    )
    return list(getattr(resp, "data", None) or [])


def fetch_dashboard(client: Any, *, is_paper: bool) -> dict:
    """Supabase에서 positions + watchlist/signal_log를 읽어 대시보드 응답을 조합한다."""
    positions = _fetch_positions(client)
    wl_rows = fetch_watchlist_rows(client)

    return {
        "positions": build_positions_summary(positions, MAX_POSITIONS),
        "watchlist_summary": build_watchlist_summary(wl_rows),
        "account": {"available": False},    # KIS 잔고 조회 미구현 — 준비 중
        "market": {"available": False},     # 지수·환율 미구현 — 준비 중
        "calendar": {"available": False},   # 경제일정 미구현 — 준비 중
        "strategy": {
            "is_paper": is_paper,
            "watchlist_count": len(wl_rows),
        },
    }


@router.get("/api/dashboard")
def get_dashboard_endpoint() -> dict:
    """대시보드 요약. DB 실패 시 500(내부 상세는 로그에만)."""
    from app.config import get_settings
    try:
        data = fetch_dashboard(get_supabase(), is_paper=get_settings().kis_is_paper)
    except Exception as exc:
        logger.warning("대시보드 조회 실패: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="대시보드를 불러오지 못했습니다") from exc
    return data
