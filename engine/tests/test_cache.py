"""일봉 캐시 테스트 — 히트/미스·TTL 만료·종목 분리·실패 시 미저장. 실네트워크 0.

시계(clock)를 주입해 TTL 경과를 결정적으로 검증한다. broker는 호출 횟수를 세는 가짜.
"""

from __future__ import annotations

import pytest

from worker.cache import DailyPriceCache


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakeBroker:
    def __init__(self) -> None:
        self.daily_calls: list[tuple[str, str]] = []

    def get_overseas_daily_prices(self, exchange: str, symbol: str):
        self.daily_calls.append((exchange, symbol))
        # 종목별로 구분되는 데이터
        return [("20260101", 100.0 + len(symbol))]


class FailBroker:
    def get_overseas_daily_prices(self, exchange: str, symbol: str):
        raise RuntimeError("KIS 500")


def test_first_get_calls_broker_and_caches() -> None:
    b = FakeBroker()
    cache = DailyPriceCache(ttl_seconds=3600, clock=FakeClock())
    out = cache.get(b, "NAS", "AAPL")
    assert out == [("20260101", 104.0)]
    assert b.daily_calls == [("NAS", "AAPL")]
    assert cache.misses == 1 and cache.hits == 0


def test_within_ttl_is_hit_no_broker_call() -> None:
    b = FakeBroker()
    clk = FakeClock()
    cache = DailyPriceCache(ttl_seconds=3600, clock=clk)
    cache.get(b, "NAS", "AAPL")
    clk.t = 3599  # TTL 안
    out = cache.get(b, "NAS", "AAPL")
    assert out == [("20260101", 104.0)]
    assert b.daily_calls == [("NAS", "AAPL")]  # KIS 호출 1회만
    assert cache.hits == 1 and cache.misses == 1


def test_expired_refetches() -> None:
    b = FakeBroker()
    clk = FakeClock()
    cache = DailyPriceCache(ttl_seconds=3600, clock=clk)
    cache.get(b, "NAS", "AAPL")
    clk.t = 3600  # 경계(age==ttl) → 만료
    cache.get(b, "NAS", "AAPL")
    assert len(b.daily_calls) == 2
    assert cache.misses == 2 and cache.hits == 0


def test_per_symbol_isolation() -> None:
    b = FakeBroker()
    clk = FakeClock()
    cache = DailyPriceCache(ttl_seconds=3600, clock=clk)
    cache.get(b, "NAS", "AAPL")
    cache.get(b, "NAS", "NVDA")
    assert b.daily_calls == [("NAS", "AAPL"), ("NAS", "NVDA")]
    # AAPL 재조회는 히트, NVDA와 독립
    cache.get(b, "NAS", "AAPL")
    assert len(b.daily_calls) == 2  # 추가 호출 없음
    assert cache.hits == 1


def test_same_symbol_different_exchange_isolated() -> None:
    b = FakeBroker()
    cache = DailyPriceCache(ttl_seconds=3600, clock=FakeClock())
    cache.get(b, "NAS", "AAPL")
    cache.get(b, "NYS", "AAPL")
    assert b.daily_calls == [("NAS", "AAPL"), ("NYS", "AAPL")]


def test_fetch_failure_propagates_and_not_cached() -> None:
    cache = DailyPriceCache(ttl_seconds=3600, clock=FakeClock())
    with pytest.raises(RuntimeError):
        cache.get(FailBroker(), "NAS", "AAPL")
    # 실패는 캐시에 저장 안 됨 → 다음에 다시 시도(여전히 실패)
    with pytest.raises(RuntimeError):
        cache.get(FailBroker(), "NAS", "AAPL")
    assert cache.misses == 0 and cache.hits == 0  # 성공 저장 없음


def test_failure_after_success_keeps_old_until_ttl() -> None:
    # 성공 캐시가 있으면 TTL 안에서는 이후 broker가 실패해도 캐시 반환(broker 안 부름)
    good = FakeBroker()
    clk = FakeClock()
    cache = DailyPriceCache(ttl_seconds=3600, clock=clk)
    cache.get(good, "NAS", "AAPL")
    clk.t = 100  # TTL 안
    out = cache.get(FailBroker(), "NAS", "AAPL")  # 히트라 FailBroker 안 부름
    assert out == [("20260101", 104.0)]
