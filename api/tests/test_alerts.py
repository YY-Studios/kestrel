"""알림 피드 로직 + 엔드포인트 테스트 — 실네트워크 0.

signal_log는 **선별**(진입 신호 enter + 추세 전환만, 반등개수만 바뀐 자잘한 변화는 제외)하고
orders는 전건을 시간순 병합한다. 순수 조합(order_to_alert·select_signal_alerts·build_alerts)을
고정하고, 엔드포인트는 get_supabase를 치환해 검증한다.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.alerts import build_alerts, order_to_alert, select_signal_alerts
from app.main import app


# --- order_to_alert -----------------------------------------------------------

def test_order_alert_buy_is_fill() -> None:
    a = order_to_alert({
        "symbol": "nvda", "side": "buy", "order_type": "buy_1", "quantity": 1,
        "price": 211.59, "status": "submitted", "realized_pnl": None,
        "created_at": "2026-07-15T14:02:09Z",
    })
    assert a["kind"] == "order" and a["symbol"] == "NVDA"
    assert a["title"] == "1차 매수 체결" and a["severity"] == "fill"
    assert a["realized_pnl"] is None


def test_order_alert_stop_loss_is_negative() -> None:
    a = order_to_alert({
        "symbol": "NVDA", "side": "sell", "order_type": "sell_sl", "quantity": 1,
        "price": 208.815, "status": "submitted", "realized_pnl": -2.775,
        "created_at": "2026-07-23T14:14:43Z",
    })
    assert a["title"] == "손절 체결" and a["severity"] == "negative"
    assert a["realized_pnl"] == -2.775


def test_order_alert_take_profit_is_positive() -> None:
    a = order_to_alert({
        "symbol": "AAPL", "side": "sell", "order_type": "sell_tp", "quantity": 2,
        "price": 247.3, "status": "submitted", "realized_pnl": 40.0,
        "created_at": "2026-07-20T03:22:00Z",
    })
    assert a["title"] == "익절 체결" and a["severity"] == "positive"


def test_order_alert_rejected_is_fail() -> None:
    a = order_to_alert({
        "symbol": "NVDA", "side": "buy", "order_type": "buy_1", "quantity": 1,
        "price": 211.59, "status": "rejected", "realized_pnl": None,
        "created_at": "2026-07-15T14:00:00Z",
    })
    assert a["severity"] == "fail" and "실패" in a["title"]


# --- select_signal_alerts: 선별 ----------------------------------------------

def _sig(symbol, decision, trend, rebound, ts, rsi=50.0) -> dict:
    return {
        "symbol": symbol, "decision": decision, "trend_ok": trend, "rebound_count": rebound,
        "rebound_required": 2, "rsi": rsi, "created_at": ts,
    }


def test_enter_signal_becomes_alert() -> None:
    alerts = select_signal_alerts([_sig("NVDA", "enter", False, 2, "2026-07-15T13:50:00Z")])
    assert len(alerts) == 1
    assert alerts[0]["title"] == "매수 신호 발생" and alerts[0]["severity"] == "signal"
    assert alerts[0]["symbol"] == "NVDA"


def test_rebound_only_change_is_filtered() -> None:
    # wait 유지 + 추세 동일, 반등 개수만 1→2 변화 → 알림 아님(자잘)
    rows = [
        _sig("TSLA", "wait", True, 1, "2026-07-15T13:00:00Z"),
        _sig("TSLA", "wait", True, 2, "2026-07-15T13:05:00Z"),
    ]
    assert select_signal_alerts(rows) == []


def test_trend_transition_becomes_alert() -> None:
    rows = [
        _sig("AAPL", "wait", False, 0, "2026-07-15T13:00:00Z"),
        _sig("AAPL", "wait", True, 1, "2026-07-15T13:10:00Z"),   # 이탈→통과
        _sig("AAPL", "wait", False, 0, "2026-07-15T13:20:00Z"),  # 통과→이탈
    ]
    alerts = select_signal_alerts(rows)
    titles = [a["title"] for a in alerts]
    assert titles == ["추세 통과", "추세 이탈"]


def test_first_row_no_trend_alert() -> None:
    # 직전 상태가 없으면 추세 전환으로 보지 않는다
    assert select_signal_alerts([_sig("NVDA", "wait", True, 0, "2026-07-15T13:00:00Z")]) == []


def test_unevaluable_and_plain_wait_filtered() -> None:
    rows = [
        _sig("NVDA", "unevaluable", None, None, "2026-07-15T13:00:00Z"),
        _sig("NVDA", "wait", None, None, "2026-07-15T13:05:00Z"),
    ]
    assert select_signal_alerts(rows) == []


# --- build_alerts: 병합·정렬·limit -------------------------------------------

def test_build_alerts_merges_and_sorts_desc() -> None:
    orders = [{
        "symbol": "NVDA", "side": "sell", "order_type": "sell_sl", "quantity": 1,
        "price": 208.815, "status": "submitted", "realized_pnl": -2.775,
        "created_at": "2026-07-23T14:14:43Z",
    }]
    signals = [_sig("NVDA", "enter", False, 2, "2026-07-15T13:50:00Z")]
    out = build_alerts(orders, signals, limit=50)
    assert out["count"] == 2
    # 최신(2026-07-23 손절)이 위
    assert out["items"][0]["title"] == "손절 체결"
    assert out["items"][1]["title"] == "매수 신호 발생"


def test_build_alerts_limit() -> None:
    orders = [
        {"symbol": "A", "side": "buy", "order_type": "buy_1", "quantity": 1, "price": 1.0,
         "status": "submitted", "realized_pnl": None, "created_at": f"2026-07-1{i}T00:00:00Z"}
        for i in range(1, 6)
    ]
    out = build_alerts(orders, [], limit=3)
    assert out["count"] == 3 and len(out["items"]) == 3


def test_build_alerts_empty() -> None:
    out = build_alerts([], [], limit=50)
    assert out["count"] == 0 and out["items"] == []


# --- 엔드포인트 ---------------------------------------------------------------

_client = TestClient(app)


class _FakeQuery:
    def __init__(self, data: list[dict]) -> None:
        self._data = data

    def select(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self):
        return type("R", (), {"data": self._data})()


class FakeSupabase:
    def __init__(self, orders=None, signals=None) -> None:
        self._map = {"orders": orders or [], "signal_log": signals or []}

    def table(self, name: str) -> Any:
        return _FakeQuery(self._map.get(name, []))


def test_endpoint_ok(monkeypatch) -> None:
    sb = FakeSupabase(
        orders=[{"symbol": "NVDA", "side": "sell", "order_type": "sell_sl", "quantity": 1,
                 "price": 208.815, "status": "submitted", "realized_pnl": -2.775,
                 "created_at": "2026-07-23T14:14:43Z"}],
        signals=[_sig("NVDA", "enter", False, 2, "2026-07-15T13:50:00Z")],
    )
    monkeypatch.setattr("app.alerts.get_supabase", lambda: sb)
    res = _client.get("/api/alerts")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 2 and body["items"][0]["title"] == "손절 체결"


def test_endpoint_empty(monkeypatch) -> None:
    monkeypatch.setattr("app.alerts.get_supabase", lambda: FakeSupabase())
    res = _client.get("/api/alerts")
    assert res.status_code == 200
    assert res.json()["count"] == 0


def test_endpoint_500_on_db_failure(monkeypatch) -> None:
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr("app.alerts.get_supabase", boom)
    res = _client.get("/api/alerts")
    assert res.status_code == 500
    assert "db down" not in res.text
