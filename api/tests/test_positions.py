"""포지션 조회 로직 + 엔드포인트 테스트 — 실네트워크 0.

Supabase·broker를 가짜로 주입. 순수 조합(build_position_item·build_positions_response)을
고정하고, 엔드포인트는 get_supabase·get_broker를 치환해 검증한다.

핵심: 손익 계산 정확 / 현재가 조회 실패 시 null 폴백(가짜 금지) / NASD→NAS 매핑 / 빈 목록.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.positions import (
    build_position_item,
    build_positions_response,
    to_price_exchange,
)


# --- 거래소 코드 매핑 (positions=주문코드 NASD → 시세코드 NAS) ------------------

def test_to_price_exchange_maps_order_codes() -> None:
    assert to_price_exchange("NASD") == "NAS"
    assert to_price_exchange("NYSE") == "NYS"
    assert to_price_exchange("AMEX") == "AMS"


def test_to_price_exchange_passthrough_unknown() -> None:
    assert to_price_exchange("NAS") == "NAS"  # 이미 시세코드면 그대로


# --- build_position_item: 손익·거리 계산 --------------------------------------

_POS = {
    "symbol": "nvda", "exchange": "NASD", "avg_price": 211.59, "quantity": 1,
    "tranche_stage": 1, "target_price": 228.5172, "stop_price": 201.0105,
    "entry_reason": "진입: 추세X 반등1/1", "created_at": "2026-07-15T14:02:09Z", "status": "open",
}


def test_build_position_item_with_price_computes_pnl() -> None:
    item = build_position_item(_POS, current_price=220.0)
    assert item["symbol"] == "NVDA" and item["exchange"] == "NASD"
    assert item["current_price"] == 220.0
    # 손익 금액 = (현재가 - 평단) * 수량
    assert item["unrealized_pnl"] == pytest.approx((220.0 - 211.59) * 1)
    # 손익률 = (현재가 - 평단) / 평단 * 100
    assert item["unrealized_pnl_pct"] == pytest.approx((220.0 - 211.59) / 211.59 * 100)
    # 목표까지(+)·손절까지(−)는 현재가 기준
    assert item["target_distance_pct"] == pytest.approx((228.5172 - 220.0) / 220.0 * 100)
    assert item["stop_distance_pct"] == pytest.approx((201.0105 - 220.0) / 220.0 * 100)
    assert item["stop_distance_pct"] < 0
    assert item["entry_reason"] == "진입: 추세X 반등1/1"
    assert item["opened_at"] == "2026-07-15T14:02:09Z"


def test_build_position_item_without_price_nulls_pnl_but_keeps_db_fields() -> None:
    # 현재가 조회 실패(None) → 손익/거리 null, 평단·수량 등 DB값은 유지(가짜 금지)
    item = build_position_item(_POS, current_price=None)
    assert item["current_price"] is None
    assert item["unrealized_pnl"] is None and item["unrealized_pnl_pct"] is None
    assert item["target_distance_pct"] is None and item["stop_distance_pct"] is None
    assert item["avg_price"] == 211.59 and item["quantity"] == 1
    assert item["tranche_stage"] == 1
    assert item["target_price"] == 228.5172 and item["stop_price"] == 201.0105


def test_build_position_item_zero_avg_guards_division() -> None:
    pos = {**_POS, "avg_price": 0}
    item = build_position_item(pos, current_price=100.0)
    assert item["unrealized_pnl_pct"] is None  # 0 나눗셈 방지


# --- build_positions_response --------------------------------------------------

def test_build_positions_response_counts_and_limit() -> None:
    prices = {"NVDA": 220.0}
    resp = build_positions_response([_POS], prices, max_positions=3)
    assert resp["held"] == 1 and resp["limit"] == 3
    assert len(resp["items"]) == 1
    assert resp["items"][0]["current_price"] == 220.0


def test_build_positions_response_empty() -> None:
    resp = build_positions_response([], {}, max_positions=3)
    assert resp["held"] == 0 and resp["items"] == []


def test_build_positions_response_missing_price_is_null() -> None:
    resp = build_positions_response([_POS], {}, max_positions=3)  # 가격 dict에 없음
    assert resp["items"][0]["current_price"] is None
    assert resp["items"][0]["unrealized_pnl"] is None


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
    def __init__(self, positions: list[dict]) -> None:
        self._positions = positions

    def table(self, name: str) -> Any:
        return _FakeQuery(self._positions if name == "positions" else [])


class _FakeBroker:
    def __init__(self, prices: dict[str, float] | None = None, fail: bool = False) -> None:
        self._prices, self._fail = prices or {}, fail
        self.calls: list[tuple[str, str]] = []

    def get_overseas_price(self, exchange: str, symbol: str) -> dict:
        self.calls.append((exchange, symbol))
        if self._fail:
            raise RuntimeError("KIS 시세 조회 실패")
        return {"symbol": symbol, "exchange": exchange, "price": self._prices.get(symbol), "raw": {}}

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _no_real_broker(monkeypatch):
    """실네트워크 0: 기본은 시세 조회 실패로 두어 실제 KIS를 부르지 않게 한다."""
    monkeypatch.setattr("app.positions.get_broker", lambda: _FakeBroker(fail=True))


def test_endpoint_ok_with_prices(monkeypatch) -> None:
    monkeypatch.setattr("app.positions.get_supabase", lambda: FakeSupabase([_POS]))
    broker = _FakeBroker(prices={"NVDA": 220.0})
    monkeypatch.setattr("app.positions.get_broker", lambda: broker)
    res = _client.get("/api/positions")
    assert res.status_code == 200
    body = res.json()
    assert body["held"] == 1 and body["limit"] == 3
    assert body["items"][0]["current_price"] == 220.0
    assert body["items"][0]["unrealized_pnl_pct"] is not None
    # NASD→NAS 매핑으로 시세 조회했는지
    assert broker.calls == [("NAS", "NVDA")]


def test_endpoint_price_failure_falls_back_to_null(monkeypatch) -> None:
    # 시세 조회 실패해도 200, current_price=null(화면 안 깨짐)
    monkeypatch.setattr("app.positions.get_supabase", lambda: FakeSupabase([_POS]))
    monkeypatch.setattr("app.positions.get_broker", lambda: _FakeBroker(fail=True))
    res = _client.get("/api/positions")
    assert res.status_code == 200
    assert res.json()["items"][0]["current_price"] is None


def test_endpoint_empty(monkeypatch) -> None:
    monkeypatch.setattr("app.positions.get_supabase", lambda: FakeSupabase([]))
    res = _client.get("/api/positions")
    assert res.status_code == 200
    assert res.json()["held"] == 0 and res.json()["items"] == []


def test_endpoint_500_on_db_failure(monkeypatch) -> None:
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr("app.positions.get_supabase", boom)
    res = _client.get("/api/positions")
    assert res.status_code == 500
    assert "db down" not in res.text  # 내부 상세 비노출
