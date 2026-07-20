"""매매내역 조회 로직 + 엔드포인트 테스트 — 실네트워크 0.

Supabase는 가짜로 주입. 순수 조합(build_order_item·build_orders_response)을 고정하고,
엔드포인트는 get_supabase를 치환해 검증한다.

핵심: 매수/매도 구분 · order_type 라벨(1·2·3차 / 익절·손절) · realized_pnl은 매도만 ·
최신순 정렬 · 빈 목록 · DB 실패 500.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.orders import (
    build_order_item,
    build_orders_response,
    detail_label,
)


# --- order_type 라벨 ----------------------------------------------------------

def test_detail_label_buy_tranches() -> None:
    assert detail_label("buy_1") == "1차"
    assert detail_label("buy_2") == "2차"
    assert detail_label("buy_3") == "3차"


def test_detail_label_sell_liquidation() -> None:
    assert detail_label("sell_tp") == "익절"
    assert detail_label("sell_sl") == "손절"


def test_detail_label_unknown_is_empty() -> None:
    assert detail_label("weird") == ""
    assert detail_label(None) == ""


# --- build_order_item ---------------------------------------------------------

_BUY = {
    "symbol": "nvda", "exchange": "NASD", "side": "buy", "order_type": "buy_1",
    "quantity": 1, "price": 211.59, "broker_order_id": "0000038044",
    "status": "submitted", "reason": "1차 매수", "realized_pnl": None,
    "created_at": "2026-07-15T14:02:09Z",
}
_SELL_SL = {
    "symbol": "TSLA", "exchange": "NASD", "side": "sell", "order_type": "sell_sl",
    "quantity": 3, "price": 218.60, "broker_order_id": "0000039000",
    "status": "submitted", "reason": "손절 — 손절가 도달", "realized_pnl": -35.4,
    "created_at": "2026-07-16T22:45:00Z",
}


def test_build_order_item_buy_fields() -> None:
    item = build_order_item(_BUY)
    assert item["symbol"] == "NVDA" and item["exchange"] == "NASD"
    assert item["side"] == "buy"
    assert item["kind_label"] == "매수" and item["detail_label"] == "1차"
    assert item["liquidation"] is None
    assert item["quantity"] == 1 and item["price"] == 211.59
    assert item["broker_order_id"] == "0000038044" and item["status"] == "submitted"
    assert item["realized_pnl"] is None  # 매수엔 실현손익 없음
    assert item["reason"] == "1차 매수"
    assert item["created_at"] == "2026-07-15T14:02:09Z"


def test_build_order_item_sell_carries_realized_pnl() -> None:
    item = build_order_item(_SELL_SL)
    assert item["side"] == "sell"
    assert item["kind_label"] == "매도" and item["detail_label"] == "손절"
    assert item["liquidation"] == "sl"
    assert item["realized_pnl"] == -35.4


def test_build_order_item_take_profit_liquidation() -> None:
    item = build_order_item({**_SELL_SL, "order_type": "sell_tp", "realized_pnl": 40.0})
    assert item["detail_label"] == "익절" and item["liquidation"] == "tp"
    assert item["realized_pnl"] == 40.0


def test_build_order_item_buy_ignores_stray_realized_pnl() -> None:
    # 매수 레코드에 realized_pnl이 잘못 들어와도 매수는 null로(가짜 손익 금지)
    item = build_order_item({**_BUY, "realized_pnl": 999.0})
    assert item["realized_pnl"] is None


# --- build_orders_response: 최신순 정렬 ---------------------------------------

def test_build_orders_response_sorts_newest_first() -> None:
    rows = [_BUY, _SELL_SL]  # 입력 순서: 오래된 → 최신
    resp = build_orders_response(rows)
    assert resp["count"] == 2
    assert resp["items"][0]["symbol"] == "TSLA"  # 2026-07-16이 최신 → 먼저
    assert resp["items"][1]["symbol"] == "NVDA"


def test_build_orders_response_empty() -> None:
    resp = build_orders_response([])
    assert resp["count"] == 0 and resp["items"] == []


# --- 엔드포인트 ---------------------------------------------------------------

_client = TestClient(app)


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
    def __init__(self, orders: list[dict]) -> None:
        self._orders = orders

    def table(self, name: str) -> Any:
        return _FakeQuery(self._orders if name == "orders" else [])


def test_endpoint_ok(monkeypatch) -> None:
    monkeypatch.setattr("app.orders.get_supabase", lambda: FakeSupabase([_BUY, _SELL_SL]))
    res = _client.get("/api/orders")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 2
    assert body["items"][0]["symbol"] == "TSLA"  # 최신순
    assert body["items"][1]["realized_pnl"] is None  # 매수


def test_endpoint_empty(monkeypatch) -> None:
    monkeypatch.setattr("app.orders.get_supabase", lambda: FakeSupabase([]))
    res = _client.get("/api/orders")
    assert res.status_code == 200
    assert res.json()["count"] == 0 and res.json()["items"] == []


def test_endpoint_500_on_db_failure(monkeypatch) -> None:
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr("app.orders.get_supabase", boom)
    res = _client.get("/api/orders")
    assert res.status_code == 500
    assert "db down" not in res.text
