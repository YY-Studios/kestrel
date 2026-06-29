"""Supabase 워치리스트 접근 테스트.

실제 Supabase에 붙지 않는다 — 가짜 클라이언트로 쿼리 체인·파싱·폴백만 검증한다.
"""

from __future__ import annotations

import pytest

from worker.config import Settings
from worker.db import get_client, get_watchlist, load_watchlist


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


def test_get_client_requires_keys() -> None:
    # 키가 비면 친절한 에러(네트워크/패키지 접근 전에 차단)
    with pytest.raises(RuntimeError):
        get_client(Settings(supabase_url="", supabase_service_key=""))
