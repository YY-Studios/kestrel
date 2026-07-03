"""대시보드 조합 로직 + 엔드포인트 테스트 — 실네트워크 0.

Supabase는 FakeSupabase로 주입. 순수 조합 함수(build_positions_summary·build_watchlist_summary)를
고정하고, 엔드포인트는 get_supabase를 치환해 검증한다.

예수금·평가자산(broker 미연결)·지수·환율·경제일정(미구현)은 available=False로 내려가는지 확인한다.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.dashboard import (
    build_positions_summary,
    build_watchlist_summary,
    fetch_dashboard,
)
from app.main import app


# --- 순수 조합 로직 --------------------------------------------------------

def test_build_positions_summary_counts_open() -> None:
    positions = [
        {"symbol": "AAPL", "exchange": "NASD", "avg_price": 100.0, "quantity": 10,
         "tranche_stage": 1, "target_price": 108.0, "stop_price": 95.0, "status": "open"},
        {"symbol": "NVDA", "exchange": "NASD", "avg_price": 150.0, "quantity": 5,
         "tranche_stage": 2, "target_price": 162.0, "stop_price": 142.5, "status": "open"},
    ]
    result = build_positions_summary(positions, max_positions=3)
    assert result["available"] is True
    assert result["held"] == 2 and result["limit"] == 3
    assert len(result["items"]) == 2


def test_build_positions_summary_fields() -> None:
    pos = [{"symbol": "AAPL", "exchange": "NASD", "avg_price": 100.0, "quantity": 10,
            "tranche_stage": 1, "target_price": 108.0, "stop_price": 95.0, "status": "open"}]
    item = build_positions_summary(pos, 3)["items"][0]
    assert item["symbol"] == "AAPL" and item["avg_price"] == 100.0
    assert item["tranche_stage"] == 1
    assert item["current_price"] is None and item["pnl_pct"] is None  # broker 미연결


def test_build_positions_summary_empty() -> None:
    result = build_positions_summary([], max_positions=3)
    assert result["available"] is True
    assert result["held"] == 0 and result["items"] == []


def test_build_watchlist_summary_counts_trend_and_signal() -> None:
    wl_rows = [
        {"symbol": "AAPL", "has_signal": True, "trend_ok": True, "rebound_count": 2, "decision": "wait"},
        {"symbol": "NVDA", "has_signal": True, "trend_ok": False, "rebound_count": 1, "decision": "wait"},
        {"symbol": "TSLA", "has_signal": True, "trend_ok": True, "rebound_count": 3, "decision": "enter"},
    ]
    result = build_watchlist_summary(wl_rows)
    assert result["available"] is True
    assert result["total"] == 3
    assert result["trend_pass"] == 2           # AAPL·TSLA
    assert result["near_signal"] == 2          # rebound_count >= 2: AAPL·TSLA
    assert result["enter_count"] == 1          # TSLA


def test_build_watchlist_summary_empty() -> None:
    result = build_watchlist_summary([])
    assert result["available"] is True and result["total"] == 0


# --- fetch_dashboard (가짜 Supabase) --------------------------------------

class _FakeQuery:
    def __init__(self, data: list[dict]) -> None:
        self._data = data

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self):
        return type("R", (), {"data": self._data})()


class FakeSupabase:
    def __init__(self, positions: list[dict], watchlist: list[dict], signals: list[dict]) -> None:
        self._map = {"positions": positions, "watchlist": watchlist, "signal_log": signals}

    def table(self, name: str) -> Any:
        return _FakeQuery(self._map.get(name, []))


def _fake_sb(positions=None, watchlist=None, signals=None) -> FakeSupabase:
    return FakeSupabase(
        positions=positions or [],
        watchlist=watchlist or [],
        signals=signals or [],
    )


def test_fetch_dashboard_structure() -> None:
    sb = _fake_sb(
        positions=[{"symbol": "AAPL", "exchange": "NASD", "avg_price": 100.0,
                    "quantity": 10, "tranche_stage": 1, "target_price": 108.0,
                    "stop_price": 95.0, "status": "open"}],
        watchlist=[{"exchange": "NAS", "symbol": "AAPL"}],
        signals=[{"symbol": "AAPL", "created_at": "2026-06-01T00:00:00Z",
                  "decision": "wait", "trend_ok": True, "rebound_count": 1}],
    )
    data = fetch_dashboard(sb, is_paper=True)
    assert "positions" in data and "watchlist_summary" in data
    assert "account" in data and "market" in data and "calendar" in data
    assert "strategy" in data


def test_fetch_dashboard_account_unavailable() -> None:
    data = fetch_dashboard(_fake_sb(), is_paper=True)
    assert data["account"]["available"] is False  # broker 미연결


def test_fetch_dashboard_market_calendar_unavailable() -> None:
    data = fetch_dashboard(_fake_sb(), is_paper=True)
    assert data["market"]["available"] is False
    assert data["calendar"]["available"] is False


def test_fetch_dashboard_strategy_shows_paper_and_count() -> None:
    sb = _fake_sb(watchlist=[{"exchange": "NAS", "symbol": "A"}, {"exchange": "NAS", "symbol": "B"}])
    data = fetch_dashboard(sb, is_paper=True)
    assert data["strategy"]["is_paper"] is True
    assert data["strategy"]["watchlist_count"] == 2


# --- 엔드포인트 -----------------------------------------------------------

_test_client = TestClient(app)


def test_endpoint_ok(monkeypatch) -> None:
    monkeypatch.setattr("app.dashboard.get_supabase", lambda: _fake_sb())
    res = _test_client.get("/api/dashboard")
    assert res.status_code == 200
    body = res.json()
    assert body["positions"]["available"] is True
    assert body["account"]["available"] is False


def test_endpoint_500_on_db_failure(monkeypatch) -> None:
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr("app.dashboard.get_supabase", boom)
    res = _test_client.get("/api/dashboard")
    assert res.status_code == 500
    assert "db down" not in res.text
