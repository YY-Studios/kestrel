"""워치리스트 조회 — Supabase watchlist + signal_log(종목별 최신 1건) 조합.

api는 Supabase를 service 키로 **서버에서** 읽는다(프론트에 키 노출 금지 — CLAUDE.md).
이 모듈은 두 계층으로 나뉜다:
  - 순수 조합 로직(build_watchlist_rows·latest_signal_by_symbol) — 테스트로 고정.
  - 얇은 조회(fetch_watchlist_rows) + 라우터(GET /api/watchlist).

engine이 signal_log에 "변화 시에만" 남긴 판단 중 종목별 최신 1건을 워치리스트에 매핑한다.
판단이 아직 없는 종목은 has_signal=False("데이터 없음")로 내려보낸다.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.supabase_client import get_supabase

logger = logging.getLogger("kestrel.api")

WATCHLIST_TABLE = "watchlist"
SIGNAL_LOG_TABLE = "signal_log"

router = APIRouter()


def latest_signal_by_symbol(signal_rows: list[dict]) -> dict[str, dict]:
    """signal_log 행들에서 종목별 최신 1건만 추린다(created_at 기준, 정렬 가정 안 함)."""
    out: dict[str, dict] = {}
    for row in signal_rows:
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        created = row.get("created_at") or ""
        prev = out.get(symbol)
        if prev is None or created > (prev.get("created_at") or ""):
            out[symbol] = row
    return out


def build_watchlist_rows(
    watchlist: list[dict], signals_by_symbol: dict[str, dict]
) -> list[dict]:
    """워치리스트 종목마다 최신 판단을 붙여 화면용 dict로. 판단 없으면 has_signal=False."""
    rows: list[dict] = []
    for w in watchlist:
        symbol = (w.get("symbol") or "").strip().upper()
        exchange = (w.get("exchange") or "").strip().upper()
        if not symbol:
            continue
        sig = signals_by_symbol.get(symbol)
        if sig is None:
            rows.append(
                {
                    "exchange": exchange, "symbol": symbol, "has_signal": False,
                    "decision": None, "trend_ok": None, "rsi": None,
                    "bollinger_signal": None, "macd_signal": None,
                    "rebound_count": None, "rebound_required": None, "updated_at": None,
                }
            )
            continue
        rows.append(
            {
                "exchange": exchange, "symbol": symbol, "has_signal": True,
                "decision": sig.get("decision"),
                "trend_ok": sig.get("trend_ok"),
                "rsi": sig.get("rsi"),
                "bollinger_signal": sig.get("bollinger_signal"),
                "macd_signal": sig.get("macd_signal"),
                "rebound_count": sig.get("rebound_count"),
                "rebound_required": sig.get("rebound_required"),
                "updated_at": sig.get("created_at"),
            }
        )
    return rows


def fetch_watchlist_rows(client: Any) -> list[dict]:
    """Supabase에서 watchlist(활성) + signal_log(최근분)를 읽어 조합한다."""
    wl_resp = (
        client.table(WATCHLIST_TABLE)
        .select("exchange,symbol")
        .eq("enabled", True)
        .order("symbol")
        .execute()
    )
    watchlist = list(getattr(wl_resp, "data", None) or [])
    sig_resp = (
        client.table(SIGNAL_LOG_TABLE)
        .select("*")
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    signal_rows = list(getattr(sig_resp, "data", None) or [])
    return build_watchlist_rows(watchlist, latest_signal_by_symbol(signal_rows))


@router.get("/api/watchlist")
def get_watchlist_endpoint() -> dict:
    """워치리스트 현황(종목별 최신 판단). DB 실패 시 500(내부 상세는 로그에만)."""
    try:
        rows = fetch_watchlist_rows(get_supabase())
    except Exception as exc:  # 연결/쿼리 실패 — 상세는 로그에만, 응답엔 노출 안 함
        logger.warning("워치리스트 조회 실패: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="워치리스트를 불러오지 못했습니다") from exc
    return {"count": len(rows), "items": rows}
