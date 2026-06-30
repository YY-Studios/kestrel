"""engine 폴링 루프 + 시나리오1 판단 연결 테스트.

broker를 가짜로 주입해 실네트워크 없이 검증한다. 두뇌(evaluate_entry)는
주입(evaluator)으로 제어하거나 실제 함수를 데이터부족 케이스로 태운다.
무한 루프는 should_run/sleep 주입으로 "몇 회 돌고 멈추게" 한다.
"""

from __future__ import annotations

import logging

from worker.indicators import (
    BollingerResult,
    EntryResult,
    MacdResult,
    PullbackResult,
    RsiResult,
    TrendResult,
    decide_entry,
)
from worker.loop import format_entry_log, parse_watchlist, poll_once, run_poll_loop


class FakeBroker:
    """get_overseas_daily_prices + get_overseas_price 흉내. fail_symbols는 예외."""

    def __init__(self, daily=None, price=124.0, fail_symbols=None) -> None:
        self.daily_calls: list[tuple[str, str]] = []
        self.price_calls: list[tuple[str, str]] = []
        self._daily = daily if daily is not None else [(f"2026010{i}", float(i)) for i in range(1, 9)]
        self._price = price
        self._fail = fail_symbols or set()

    def get_overseas_daily_prices(self, exchange: str, symbol: str):
        self.daily_calls.append((exchange, symbol))
        if symbol in self._fail:
            raise RuntimeError("일봉 조회 실패")
        return self._daily

    def get_overseas_price(self, exchange: str, symbol: str) -> dict:
        self.price_calls.append((exchange, symbol))
        return {"symbol": symbol, "exchange": exchange, "price": self._price, "raw": {}}

    def place_overseas_order(self, *a, **k):  # 드라이런 단계에선 절대 호출되면 안 됨
        raise AssertionError("드라이런 단계에서 실주문(place_overseas_order)이 호출되면 안 된다")


def _entry(enter: bool, evaluable: bool = True, rebound: int = 2) -> EntryResult:
    return EntryResult(
        enter=enter,
        evaluable=evaluable,
        trend=TrendResult(21.0, 20.0, 22.0, True, True),
        pullback=PullbackResult(100.0, 92.0, 0.08, True, True),
        rsi=RsiResult(31.0, True, True),
        bollinger=BollingerResult(10.0, 12.0, 8.0, 8.5, True, True),
        macd=MacdResult(-0.1, -0.2, 0.1, True, False),
        rebound_count=rebound,
        rebound_required=2,
    )


def _counted_should_run(n: int):
    state = {"i": 0}

    def should_run() -> bool:
        state["i"] += 1
        return state["i"] <= n

    return should_run


def test_parse_watchlist() -> None:
    assert parse_watchlist(["NAS:AAPL", "nas:tsla", "", "bad"]) == [("NAS", "AAPL"), ("NAS", "TSLA")]


def test_poll_once_fetches_daily_and_price_per_symbol() -> None:
    broker = FakeBroker()
    poll_once(broker, [("NAS", "AAPL"), ("NAS", "TSLA")], evaluator=lambda *a, **k: _entry(False))
    assert broker.daily_calls == [("NAS", "AAPL"), ("NAS", "TSLA")]
    assert broker.price_calls == [("NAS", "AAPL"), ("NAS", "TSLA")]


def test_poll_once_passes_closes_and_price_to_evaluator() -> None:
    broker = FakeBroker(daily=[("20260101", 10.0), ("20260102", 11.0)], price=12.5)
    captured: dict = {}

    def evaluator(closes, current_price=None, **kw):
        captured["closes"] = closes
        captured["price"] = current_price
        return _entry(False)

    poll_once(broker, [("NAS", "AAPL")], evaluator=evaluator)
    assert captured["closes"] == [10.0, 11.0]  # (date, close) → close 리스트
    assert captured["price"] == 12.5


def test_poll_once_logs_entry_signal(caplog) -> None:
    broker = FakeBroker()
    with caplog.at_level(logging.INFO, logger="kestrel.engine"):
        poll_once(broker, [("NAS", "AAPL")], evaluator=lambda *a, **k: _entry(True))
    assert any("AAPL" in m and "진입" in m for m in caplog.messages)


def test_poll_once_logs_wait(caplog) -> None:
    broker = FakeBroker()
    with caplog.at_level(logging.INFO, logger="kestrel.engine"):
        poll_once(broker, [("NAS", "AAPL")], evaluator=lambda *a, **k: _entry(False))
    assert any("대기" in m for m in caplog.messages)


def test_poll_once_skips_symbol_on_fetch_error() -> None:
    broker = FakeBroker(fail_symbols={"AAPL"})
    # AAPL은 일봉 조회 실패 → 건너뛰고 TSLA는 계속
    poll_once(broker, [("NAS", "AAPL"), ("NAS", "TSLA")], evaluator=lambda *a, **k: _entry(False))
    assert ("NAS", "TSLA") in broker.daily_calls
    assert ("NAS", "TSLA") in broker.price_calls


def test_poll_once_data_insufficient_logs_not_evaluable(caplog) -> None:
    # 일봉이 적으면 실제 evaluate_entry가 evaluable=False → "판단불가" 로그, 예외 없음
    broker = FakeBroker(daily=[("20260101", 10.0), ("20260102", 11.0), ("20260103", 12.0)])
    with caplog.at_level(logging.INFO, logger="kestrel.engine"):
        poll_once(broker, [("NAS", "AAPL")])  # 실제 evaluate_entry 사용(주입 안 함)
    assert any("판단불가" in m for m in caplog.messages)


def test_run_poll_loop_stops_and_survives_errors() -> None:
    broker = FakeBroker(fail_symbols={"AAPL"})
    run_poll_loop(
        broker,
        [("NAS", "AAPL")],
        interval=0,
        should_run=_counted_should_run(3),
        sleep=lambda _x: None,
        evaluator=lambda *a, **k: _entry(False),
    )
    assert len(broker.daily_calls) == 3  # 에러에도 3주기 계속


# --- 로그 포맷 ------------------------------------------------------------

def _full_entry(enter, evaluable, trend_passed=True, drop=0.062, rebound=2):
    trend = TrendResult(21.0, 20.0, 22.0, True, trend_passed)
    pb = PullbackResult(100.0, 93.8, drop, True, True)
    rsi_r = RsiResult(31.0, True, rebound >= 1)
    bb = BollingerResult(10.0, 12.0, 8.0, 8.5, True, rebound >= 2)
    macd_r = MacdResult(-0.1, -0.2, 0.1, True, rebound >= 3)
    return decide_entry(trend, pb, rsi_r, bb, macd_r) if evaluable else EntryResult(
        False, False, trend, pb, rsi_r, bb, macd_r, rebound, 2
    )


def test_format_entry_log_enter() -> None:
    s = format_entry_log("NAS", "AAPL", _full_entry(enter=True, evaluable=True, rebound=2))
    assert "AAPL" in s and "진입" in s and "2/3" in s


def test_format_entry_log_not_evaluable() -> None:
    s = format_entry_log("NAS", "AAPL", _full_entry(enter=False, evaluable=False))
    assert "판단불가" in s


# --- recorder 연동 --------------------------------------------------------

class _RecorderSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def record_if_changed(self, exchange, symbol, result) -> bool:
        self.calls.append((exchange, symbol))
        return True


def test_poll_once_calls_recorder_per_symbol() -> None:
    broker = FakeBroker()
    spy = _RecorderSpy()
    poll_once(broker, [("NAS", "AAPL"), ("NAS", "TSLA")], evaluator=lambda *a, **k: _entry(False), recorder=spy)
    assert spy.calls == [("NAS", "AAPL"), ("NAS", "TSLA")]


def test_poll_once_without_recorder_ok() -> None:
    # recorder 미지정이면 기록 호출 없이 정상 동작(기존 동작 보존)
    broker = FakeBroker()
    poll_once(broker, [("NAS", "AAPL")], evaluator=lambda *a, **k: _entry(False))
    assert broker.daily_calls == [("NAS", "AAPL")]


# --- executor 연동 (주문 처리) --------------------------------------------

class _ExecutorSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def handle(self, exchange, symbol, price, result) -> None:
        self.calls.append((exchange, symbol))


def test_poll_once_calls_executor_on_entry() -> None:
    broker = FakeBroker(price=100.0)
    spy = _ExecutorSpy()
    poll_once(broker, [("NAS", "AAPL")], evaluator=lambda *a, **k: _entry(True), executor=spy)
    assert spy.calls == [("NAS", "AAPL")]


def test_poll_once_no_executor_on_wait() -> None:
    # 진입 신호가 아니면 executor를 호출하지 않는다
    broker = FakeBroker(price=100.0)
    spy = _ExecutorSpy()
    poll_once(broker, [("NAS", "AAPL")], evaluator=lambda *a, **k: _entry(False), executor=spy)
    assert spy.calls == []


def test_poll_once_no_executor_ok2() -> None:
    # executor 미지정이면 진입 신호여도 주문 처리 없이 정상(실주문 0)
    broker = FakeBroker(price=100.0)
    poll_once(broker, [("NAS", "AAPL")], evaluator=lambda *a, **k: _entry(True))
    assert broker.daily_calls == [("NAS", "AAPL")]
