"""Supabase 워치리스트 접근 테스트.

실제 Supabase에 붙지 않는다 — 가짜 클라이언트로 쿼리 체인·파싱·폴백만 검증한다.
"""

from __future__ import annotations

import pytest

from worker.config import Settings
from worker.db import (
    SignalRecorder,
    close_position,
    entry_result_to_record,
    get_client,
    get_held_symbols,
    get_open_positions,
    get_recent_orders,
    get_watchlist,
    insert_order,
    insert_signal_log,
    load_strategy_settings,
    load_watchlist,
    upsert_position,
)
from worker.strategy_config import DEFAULTS
from worker.indicators import (
    BollingerResult,
    EntryResult,
    MacdResult,
    PullbackResult,
    RsiResult,
    TrendResult,
)


class _FakeQuery:
    """supabase-py의 table().select().eq().order().execute() 체인을 흉내낸다."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        return type("Resp", (), {"data": self._rows})()


class FakeClient:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.tables: list[str] = []

    def table(self, name: str) -> _FakeQuery:
        self.tables.append(name)
        return _FakeQuery(self._rows)


class RaisingClient:
    def table(self, name: str):
        raise RuntimeError("connection refused")


def test_get_watchlist_parses_rows() -> None:
    client = FakeClient([{"exchange": "NAS", "symbol": "AAPL"}, {"exchange": "nys", "symbol": "ibm"}])
    assert get_watchlist(client) == [("NAS", "AAPL"), ("NYS", "IBM")]
    assert client.tables == ["watchlist"]


def test_get_watchlist_skips_incomplete_rows() -> None:
    client = FakeClient([{"exchange": "NAS", "symbol": ""}, {"exchange": "", "symbol": "X"}, {"exchange": "NAS", "symbol": "TSLA"}])
    assert get_watchlist(client) == [("NAS", "TSLA")]


def test_get_watchlist_empty() -> None:
    assert get_watchlist(FakeClient([])) == []


def test_load_watchlist_returns_db_rows() -> None:
    client = FakeClient([{"exchange": "NAS", "symbol": "AAPL"}])
    assert load_watchlist(client, default=[("NAS", "FALLBACK")]) == [("NAS", "AAPL")]


def test_load_watchlist_falls_back_on_empty() -> None:
    fallback = [("NAS", "AAPL")]
    assert load_watchlist(FakeClient([]), default=fallback) == fallback


def test_load_watchlist_falls_back_on_error() -> None:
    fallback = [("NAS", "AAPL")]
    # DB 접근이 예외를 던져도 루프가 죽지 않게 폴백
    assert load_watchlist(RaisingClient(), default=fallback) == fallback


def test_load_strategy_settings_returns_validated_row() -> None:
    client = FakeClient([{"id": 1, "rsi_threshold": 30, "rebound_required": 1}])
    out = load_strategy_settings(client)
    assert out is not None
    assert out["rsi_threshold"] == 30 and out["rebound_required"] == 1
    assert out["take_profit_pct"] == DEFAULTS["take_profit_pct"]  # 누락 필드는 기본
    assert client.tables == ["strategy_settings"]


def test_load_strategy_settings_out_of_range_falls_back() -> None:
    # DB에 직접 넣은 이상값은 그 필드만 기본값으로
    client = FakeClient([{"id": 1, "stop_loss_pct": 0.9}])
    out = load_strategy_settings(client)
    assert out is not None and out["stop_loss_pct"] == DEFAULTS["stop_loss_pct"]


def test_load_strategy_settings_empty_returns_none() -> None:
    assert load_strategy_settings(FakeClient([])) is None


def test_load_strategy_settings_error_returns_none() -> None:
    # 테이블 없음/DB 실패 → None(호출부가 기본값 폴백)
    assert load_strategy_settings(RaisingClient()) is None


def test_get_client_requires_keys() -> None:
    # 키가 비면 친절한 에러(네트워크/패키지 접근 전에 차단)
    with pytest.raises(RuntimeError):
        get_client(Settings(supabase_url="", supabase_service_key=""))


# --- 신호 로그 (DB write + 변화 시에만 기록) -------------------------------

def _entry(enter: bool, evaluable: bool = True, trend_passed: bool = True, rebound: int = 2) -> EntryResult:
    return EntryResult(
        enter=enter,
        evaluable=evaluable,
        trend=TrendResult(21.0, 20.0, 22.0, True, trend_passed),
        pullback=PullbackResult(100.0, 92.0, 0.08, True, True),
        rsi=RsiResult(31.0, True, rebound >= 1),
        bollinger=BollingerResult(10.0, 12.0, 8.0, 8.5, True, rebound >= 2),
        macd=MacdResult(-0.1, -0.2, 0.1, True, rebound >= 3),
        rebound_count=rebound,
        rebound_required=2,
    )


class FakeInsertClient:
    def __init__(self) -> None:
        self.inserted: list[tuple[str, dict]] = []
        self._t = ""
        self._rec: dict = {}

    def table(self, name: str):
        self._t = name
        return self

    def insert(self, record: dict):
        self._rec = record
        return self

    def execute(self):
        self.inserted.append((self._t, self._rec))
        return type("Resp", (), {"data": [self._rec]})()


class RaisingInsertClient:
    def table(self, name: str):
        return self

    def insert(self, record: dict):
        return self

    def execute(self):
        raise RuntimeError("insert failed")


def test_entry_result_to_record_enter() -> None:
    rec = entry_result_to_record("NAS", "AAPL", _entry(enter=True, rebound=2))
    assert rec["exchange"] == "NAS" and rec["symbol"] == "AAPL"
    assert rec["decision"] == "enter"
    assert rec["trend_ok"] is True
    assert rec["rebound_count"] == 2 and rec["rebound_required"] == 2
    assert rec["evaluable"] is True
    assert rec["bollinger_signal"] is True and rec["macd_signal"] is False


def test_entry_result_to_record_wait_and_unevaluable() -> None:
    assert entry_result_to_record("NAS", "AAPL", _entry(enter=False, evaluable=True))["decision"] == "wait"
    assert entry_result_to_record("NAS", "AAPL", _entry(enter=False, evaluable=False))["decision"] == "unevaluable"


def test_insert_signal_log_calls_table_insert() -> None:
    client = FakeInsertClient()
    insert_signal_log(client, {"symbol": "AAPL"})
    assert client.inserted == [("signal_log", {"symbol": "AAPL"})]


def test_recorder_first_observation_records() -> None:
    client = FakeInsertClient()
    rec = SignalRecorder(client)
    assert rec.record_if_changed("NAS", "AAPL", _entry(enter=False)) is True
    assert len(client.inserted) == 1


def test_recorder_suppresses_unchanged() -> None:
    client = FakeInsertClient()
    rec = SignalRecorder(client)
    rec.record_if_changed("NAS", "AAPL", _entry(enter=False, rebound=2))
    # 동일 판단 반복 → 기록 생략
    assert rec.record_if_changed("NAS", "AAPL", _entry(enter=False, rebound=2)) is False
    assert len(client.inserted) == 1


def test_recorder_records_on_change() -> None:
    client = FakeInsertClient()
    rec = SignalRecorder(client)
    rec.record_if_changed("NAS", "AAPL", _entry(enter=False, rebound=1))  # wait, rebound1
    rec.record_if_changed("NAS", "AAPL", _entry(enter=True, rebound=2))   # enter → 변화
    assert len(client.inserted) == 2


def test_recorder_db_failure_does_not_raise_and_retries() -> None:
    rec = SignalRecorder(RaisingInsertClient())
    # 실패해도 예외 전파 안 함(루프 안 죽음)
    assert rec.record_if_changed("NAS", "AAPL", _entry(enter=False)) is False
    # 실패 시 직전 상태 미갱신 → 다음 동일 판단도 다시 시도(여전히 실패하지만 예외 없음)
    assert rec.record_if_changed("NAS", "AAPL", _entry(enter=False)) is False


# --- positions (보유 상태) -------------------------------------------------

class _PosQuery:
    """table().select().eq()...execute() / upsert()/update() 체인 흉내."""

    def __init__(self, parent: "PositionsClient", rows: list[dict]) -> None:
        self._parent = parent
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def execute(self):
        return type("Resp", (), {"data": self._rows})()

    def upsert(self, record, **_k):
        self._parent.upserts.append(record)
        return self

    def update(self, patch, **_k):
        self._parent.updates.append(patch)
        return self


class PositionsClient:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or []
        self.upserts: list[dict] = []
        self.updates: list[dict] = []

    def table(self, name: str) -> _PosQuery:
        return _PosQuery(self, list(self._rows))


class RaisingClient2:
    def table(self, name: str):
        raise RuntimeError("db down")


def test_get_open_positions_parses() -> None:
    client = PositionsClient([
        {"symbol": "AAPL", "avg_price": 138.2, "quantity": 15, "tranche_stage": 2, "status": "open"},
        {"symbol": "TSLA", "avg_price": 240.0, "quantity": 5, "tranche_stage": 1, "status": "open"},
    ])
    rows = get_open_positions(client)
    assert len(rows) == 2
    assert rows[0]["symbol"] == "AAPL" and rows[0]["tranche_stage"] == 2


def test_get_held_symbols() -> None:
    client = PositionsClient([
        {"symbol": "AAPL", "status": "open"},
        {"symbol": "TSLA", "status": "open"},
    ])
    assert get_held_symbols(client) == {"AAPL", "TSLA"}


def test_get_held_symbols_falls_back_on_error() -> None:
    # DB 실패 → 빈 집합(루프가 죽지 않게)
    assert get_held_symbols(RaisingClient2()) == set()


def test_get_open_positions_falls_back_on_error() -> None:
    assert get_open_positions(RaisingClient2()) == []


def test_upsert_position_calls_upsert() -> None:
    client = PositionsClient()
    pos = {"exchange": "NASD", "symbol": "AAPL", "avg_price": 138.2, "quantity": 15, "status": "open"}
    upsert_position(client, pos)
    assert client.upserts == [pos]


def test_close_position_marks_closed() -> None:
    client = PositionsClient()
    close_position(client, "AAPL")
    assert len(client.updates) == 1
    assert client.updates[0]["status"] == "closed"
    assert "closed_at" in client.updates[0]


# --- orders (체결 내역, 누적) ----------------------------------------------

class _OrdersQuery:
    def __init__(self, parent: "OrdersClient", rows: list[dict]) -> None:
        self._parent = parent
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def insert(self, record):
        self._parent.inserted.append(record)
        return self

    def execute(self):
        return type("Resp", (), {"data": self._rows})()


class OrdersClient:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or []
        self.inserted: list[dict] = []

    def table(self, name: str) -> _OrdersQuery:
        return _OrdersQuery(self, list(self._rows))


def test_insert_order_records_row() -> None:
    client = OrdersClient()
    rec = {"exchange": "NASD", "symbol": "AAPL", "side": "buy", "quantity": 5, "price": 295.0}
    insert_order(client, rec)
    assert client.inserted == [rec]


def test_get_recent_orders_parses_and_limits() -> None:
    client = OrdersClient([{"symbol": "AAPL"}, {"symbol": "TSLA"}, {"symbol": "NVDA"}])
    rows = get_recent_orders(client, limit=2)
    assert len(rows) == 2
    assert rows[0]["symbol"] == "AAPL"


def test_get_recent_orders_falls_back_on_error() -> None:
    assert get_recent_orders(RaisingClient2(), limit=10) == []
