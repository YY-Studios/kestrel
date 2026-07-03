"""워치리스트 조회 로직 + 엔드포인트 테스트 — 실네트워크 0.

Supabase는 가짜(FakeSupabase)로 주입한다. 순수 조합 로직(build_watchlist_rows·
latest_signal_by_symbol)을 고정하고, 엔드포인트는 get_supabase를 가짜로 치환해 검증한다.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.watchlist import (
    build_watchlist_rows,
    fetch_watchlist_rows,
    latest_signal_by_symbol,
)


# --- 순수 조합 로직 --------------------------------------------------------

def test_latest_signal_by_symbol_picks_newest() -> None:
    rows = [
        {"symbol": "AAPL", "created_at": "2026-06-01T00:00:00Z", "decision": "wait"},
        {"symbol": "AAPL", "created_at": "2026-06-10T00:00:00Z", "decision": "enter"},
        {"symbol": "TSLA", "created_at": "2026-06-05T00:00:00Z", "decision": "wait"},
    ]
    latest = latest_signal_by_symbol(rows)
    assert latest["AAPL"]["decision"] == "enter"  # 최신 1건
    assert latest["TSLA"]["decision"] == "wait"


def test_build_rows_maps_signal_fields() -> None:
    watchlist = [{"exchange": "NAS", "symbol": "AAPL"}]
    signals = {
        "AAPL": {
            "decision": "wait", "trend_ok": True, "rsi": 31.0,
            "bollinger_signal": True, "macd_signal": False,
            "rebound_count": 2, "rebound_required": 2,
            "created_at": "2026-06-10T00:00:00Z",
        }
    }
    rows = build_watchlist_rows(watchlist, signals)
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == "AAPL" and r["exchange"] == "NAS"
    assert r["has_signal"] is True
    assert r["trend_ok"] is True and r["rsi"] == 31.0
    assert r["bollinger_signal"] is True and r["macd_signal"] is False
    assert r["rebound_count"] == 2 and r["decision"] == "wait"
    assert r["updated_at"] == "2026-06-10T00:00:00Z"


def test_build_rows_no_signal_marks_missing() -> None:
    # signal_log에 아직 판단이 없는 종목 → has_signal False, 지표 None
    rows = build_watchlist_rows([{"exchange": "NAS", "symbol": "NVDA"}], {})
    assert rows[0]["has_signal"] is False
    assert rows[0]["decision"] is None and rows[0]["trend_ok"] is None


def test_build_rows_skips_blank_symbol() -> None:
    rows = build_watchlist_rows([{"exchange": "NAS", "symbol": ""}], {})
    assert rows == []


# --- 얇은 조회 (가짜 Supabase) --------------------------------------------

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
    def __init__(self, watchlist: list[dict], signals: list[dict]) -> None:
        self._watchlist, self._signals = watchlist, signals

    def table(self, name: str) -> Any:
        return _FakeQuery(self._watchlist if name == "watchlist" else self._signals)


def test_fetch_combines_watchlist_and_latest_signal() -> None:
    fake = FakeSupabase(
        watchlist=[{"exchange": "NAS", "symbol": "AAPL"}, {"exchange": "NAS", "symbol": "NVDA"}],
        signals=[
            {"symbol": "AAPL", "created_at": "2026-06-01T00:00:00Z", "decision": "wait", "rsi": 40},
            {"symbol": "AAPL", "created_at": "2026-06-10T00:00:00Z", "decision": "enter", "rsi": 31},
        ],
    )
    rows = fetch_watchlist_rows(fake)
    by_symbol = {r["symbol"]: r for r in rows}
    assert by_symbol["AAPL"]["decision"] == "enter"  # 최신 반영
    assert by_symbol["NVDA"]["has_signal"] is False   # 판단 없음


# --- 엔드포인트 -----------------------------------------------------------

client = TestClient(app)


def test_endpoint_returns_items(monkeypatch) -> None:
    fake = FakeSupabase(
        watchlist=[{"exchange": "NAS", "symbol": "AAPL"}],
        signals=[{"symbol": "AAPL", "created_at": "2026-06-10T00:00:00Z", "decision": "wait"}],
    )
    monkeypatch.setattr("app.watchlist.get_supabase", lambda: fake)
    res = client.get("/api/watchlist")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1 and body["items"][0]["symbol"] == "AAPL"


def test_endpoint_empty_watchlist_ok(monkeypatch) -> None:
    monkeypatch.setattr("app.watchlist.get_supabase", lambda: FakeSupabase([], []))
    res = client.get("/api/watchlist")
    assert res.status_code == 200 and res.json() == {"count": 0, "items": []}


def test_endpoint_500_on_db_failure(monkeypatch) -> None:
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.watchlist.get_supabase", boom)
    res = client.get("/api/watchlist")
    assert res.status_code == 500
    # 에러 메시지에 내부 상세/키가 새지 않는다
    assert "db down" not in res.text
