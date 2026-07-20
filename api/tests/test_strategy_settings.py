"""전략설정 조회/저장 로직 + 엔드포인트 테스트 — 실네트워크 0.

순수 검증(coerce_and_validate·merged_settings·validate_full)을 고정하고, 엔드포인트는
get_supabase를 치환해 검증한다. 핵심: 안전 범위 밖 → 400(서버 검증), 기본값 폴백, 저장.
engine 반영은 이번 슬라이스 밖(저장까지만).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.strategy_settings import (
    DEFAULTS,
    SPECS,
    coerce_and_validate,
    merged_settings,
    validate_full,
)


# --- 스펙/기본값 ---------------------------------------------------------------

def test_defaults_match_current_strategy() -> None:
    # 현재 전략 기본값(indicators/orders/execution)과 일치
    assert DEFAULTS["rsi_threshold"] == 35
    assert DEFAULTS["pullback_min"] == 0.05 and DEFAULTS["pullback_max"] == 0.10
    assert DEFAULTS["rebound_required"] == 2
    assert DEFAULTS["take_profit_pct"] == 0.08 and DEFAULTS["stop_loss_pct"] == 0.05
    assert DEFAULTS["max_positions"] == 3


def test_every_default_is_within_its_range() -> None:
    by_key = {s["key"]: s for s in SPECS}
    for key, val in DEFAULTS.items():
        s = by_key[key]
        assert s["min"] <= val <= s["max"], key


# --- coerce_and_validate: 범위/타입 -------------------------------------------

def test_coerce_valid_values() -> None:
    cleaned = coerce_and_validate({"rsi_threshold": 40, "take_profit_pct": 0.12})
    assert cleaned == {"rsi_threshold": 40, "take_profit_pct": 0.12}


def test_coerce_int_fields_are_int() -> None:
    cleaned = coerce_and_validate({"rebound_required": 3, "max_positions": 2})
    assert cleaned["rebound_required"] == 3 and isinstance(cleaned["rebound_required"], int)


def test_coerce_out_of_range_raises() -> None:
    with pytest.raises(ValueError):
        coerce_and_validate({"rsi_threshold": 50})   # max 45
    with pytest.raises(ValueError):
        coerce_and_validate({"stop_loss_pct": 0.5})  # max 0.10
    with pytest.raises(ValueError):
        coerce_and_validate({"rebound_required": 0})  # min 1


def test_coerce_unknown_key_raises() -> None:
    with pytest.raises(ValueError):
        coerce_and_validate({"danger_flag": True})


def test_coerce_non_numeric_raises() -> None:
    with pytest.raises(ValueError):
        coerce_and_validate({"rsi_threshold": "abc"})


# --- merged_settings / validate_full ------------------------------------------

def test_merged_fills_defaults_and_overrides() -> None:
    merged = merged_settings({"rsi_threshold": 30}, {"take_profit_pct": 0.10})
    assert merged["rsi_threshold"] == 30       # current
    assert merged["take_profit_pct"] == 0.10   # patch
    assert merged["stop_loss_pct"] == DEFAULTS["stop_loss_pct"]  # default
    assert set(merged.keys()) == set(DEFAULTS.keys())  # 여분 컬럼 제거


def test_validate_full_rejects_pullback_min_gt_max() -> None:
    bad = {**DEFAULTS, "pullback_min": 0.10, "pullback_max": 0.05}
    with pytest.raises(ValueError):
        validate_full(bad)


def test_validate_full_ok() -> None:
    assert validate_full({**DEFAULTS}) == {**DEFAULTS}


# --- 엔드포인트 ---------------------------------------------------------------

_client = TestClient(app)


class _FakeQuery:
    def __init__(self, store: dict) -> None:
        self._store = store

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self):
        row = self._store.get("row")
        return type("R", (), {"data": [row] if row else []})()

    def upsert(self, record, *a, **k):
        self._store["row"] = record
        return self

    def order(self, *a, **k): return self


class FakeSupabase:
    def __init__(self, row: dict | None = None) -> None:
        self.store: dict = {"row": row}

    def table(self, name: str) -> Any:
        return _FakeQuery(self.store)


def test_get_returns_defaults_when_empty(monkeypatch) -> None:
    monkeypatch.setattr("app.strategy_settings.get_supabase", lambda: FakeSupabase(None))
    res = _client.get("/api/strategy-settings")
    assert res.status_code == 200
    body = res.json()
    assert body["settings"]["rsi_threshold"] == DEFAULTS["rsi_threshold"]
    assert isinstance(body["spec"], list) and len(body["spec"]) == len(SPECS)


def test_get_returns_saved_row(monkeypatch) -> None:
    row = {"id": 1, **DEFAULTS, "rsi_threshold": 28}
    monkeypatch.setattr("app.strategy_settings.get_supabase", lambda: FakeSupabase(row))
    res = _client.get("/api/strategy-settings")
    assert res.json()["settings"]["rsi_threshold"] == 28
    assert res.json()["persisted"] is True


def test_get_falls_back_to_defaults_when_table_missing(monkeypatch) -> None:
    # 테이블 미생성 등 조회 실패여도 기본값으로 폴백(200) — 화면이 뜨게. persisted=False로 구분.
    def boom():
        raise RuntimeError("relation strategy_settings does not exist")
    monkeypatch.setattr("app.strategy_settings.get_supabase", boom)
    res = _client.get("/api/strategy-settings")
    assert res.status_code == 200
    assert res.json()["settings"]["rsi_threshold"] == DEFAULTS["rsi_threshold"]
    assert res.json()["persisted"] is False


def test_post_saves_valid_and_persists(monkeypatch) -> None:
    fake = FakeSupabase(None)
    monkeypatch.setattr("app.strategy_settings.get_supabase", lambda: fake)
    res = _client.post("/api/strategy-settings", json={"settings": {"rsi_threshold": 40}})
    assert res.status_code == 200
    assert res.json()["settings"]["rsi_threshold"] == 40
    assert fake.store["row"]["rsi_threshold"] == 40  # 저장됨
    assert fake.store["row"]["id"] == 1              # 단일 행


def test_post_out_of_range_returns_400(monkeypatch) -> None:
    monkeypatch.setattr("app.strategy_settings.get_supabase", lambda: FakeSupabase(None))
    res = _client.post("/api/strategy-settings", json={"settings": {"stop_loss_pct": 0.9}})
    assert res.status_code == 400


def test_post_unknown_key_returns_400(monkeypatch) -> None:
    monkeypatch.setattr("app.strategy_settings.get_supabase", lambda: FakeSupabase(None))
    res = _client.post("/api/strategy-settings", json={"settings": {"evil": 1}})
    assert res.status_code == 400


def test_post_pullback_cross_validation_returns_400(monkeypatch) -> None:
    monkeypatch.setattr("app.strategy_settings.get_supabase", lambda: FakeSupabase(None))
    res = _client.post(
        "/api/strategy-settings",
        json={"settings": {"pullback_min": 0.10, "pullback_max": 0.06}},
    )
    assert res.status_code == 400


def test_post_500_on_db_failure(monkeypatch) -> None:
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr("app.strategy_settings.get_supabase", boom)
    res = _client.post("/api/strategy-settings", json={"settings": {"rsi_threshold": 40}})
    assert res.status_code == 500
    assert "db down" not in res.text
