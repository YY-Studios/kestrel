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
from worker.loop import (
    check_positions_once,
    format_entry_log,
    parse_watchlist,
    poll_once,
    resolve_watchlist_override,
    run_poll_loop,
)


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


def test_resolve_watchlist_override_unset_is_empty() -> None:
    # 미설정/빈값 → 빈 목록(override 없음 → 호출부는 DB 워치리스트를 쓴다)
    assert resolve_watchlist_override(None) == []
    assert resolve_watchlist_override("") == []
    assert resolve_watchlist_override("   ") == []


def test_resolve_watchlist_override_limits_to_given_symbols() -> None:
    # 검증 통제용: 값이 있으면 그 종목만(대문자 정규화, 형식오류 무시)
    assert resolve_watchlist_override("nas:nvda") == [("NAS", "NVDA")]
    assert resolve_watchlist_override("NAS:NVDA,NYS:BA,bad") == [("NAS", "NVDA"), ("NYS", "BA")]


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
        self.stop_calls: list[tuple[str, float | None]] = []

    def handle(self, exchange, symbol, price, result) -> None:
        self.calls.append((exchange, symbol))

    def handle_position(self, position, current_price) -> None:
        self.stop_calls.append((position["symbol"], current_price))


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


# --- 포지션 점검(손절) ----------------------------------------------------

def test_check_positions_once_fetches_price_and_calls_stop() -> None:
    broker = FakeBroker(price=94.0)
    spy = _ExecutorSpy()
    positions = [{"symbol": "AAPL", "exchange": "NASD"}]
    check_positions_once(broker, positions, spy)
    # 포지션 거래소(NASD) → 시세 조회는 NAS로 매핑
    assert broker.price_calls == [("NAS", "AAPL")]
    assert spy.stop_calls == [("AAPL", 94.0)]


def test_check_positions_once_survives_error() -> None:
    class _BadBroker(FakeBroker):
        def get_overseas_price(self, exchange, symbol):
            raise RuntimeError("boom")

    spy = _ExecutorSpy()
    check_positions_once(_BadBroker(), [{"symbol": "AAPL", "exchange": "NASD"}], spy)
    assert spy.stop_calls == []  # 조회 실패 → 스킵, 예외 없음


# --- 포지션 점검(분할 2·3차 추가매수) — 청산 우선 ---------------------------

class _TrancheSpy:
    """handle_position 반환값(청산 시도 여부)을 제어하고 추가매수 호출을 기록하는 스파이."""

    def __init__(self, sold: bool = False) -> None:
        self._sold = sold
        self.stop_calls: list[tuple[str, float | None]] = []
        self.add_calls: list[tuple[str, float | None]] = []

    def handle_position(self, position, current_price) -> bool:
        self.stop_calls.append((position["symbol"], current_price))
        return self._sold

    def handle_add_tranche(self, position, current_price, entry) -> None:
        self.add_calls.append((position["symbol"], current_price))


def test_check_positions_no_add_when_exit_attempted() -> None:
    # 핵심(청산 우선): 손절/익절이 트리거되면 그 주기엔 추가매수 점검 자체를 안 한다
    broker = FakeBroker(price=94.0)
    spy = _TrancheSpy(sold=True)
    positions = [{"symbol": "AAPL", "exchange": "NASD", "tranche_stage": 1}]
    check_positions_once(broker, positions, spy)
    assert spy.add_calls == []
    assert broker.daily_calls == []  # 일봉 조회도 없음


def test_check_positions_add_when_not_sold_and_stage_left() -> None:
    # 청산 없음 + tranche_stage<3 → 일봉으로 반등 재평가 후 추가매수 점검
    broker = FakeBroker(price=96.0)
    spy = _TrancheSpy(sold=False)
    seen: list[float | None] = []

    def evaluator(closes, current_price=None):
        seen.append(current_price)
        return _entry(False, rebound=2)

    positions = [{"symbol": "AAPL", "exchange": "NASD", "tranche_stage": 1}]
    check_positions_once(broker, positions, spy, evaluator=evaluator)
    assert broker.daily_calls == [("NAS", "AAPL")]  # NASD→NAS 매핑으로 일봉 조회
    assert seen == [96.0]  # 현재가로 반등 재평가
    assert spy.add_calls == [("AAPL", 96.0)]


def test_check_positions_no_add_when_stage_complete() -> None:
    # 3차 완료 포지션은 일봉 조회 자체를 생략(API 절약)
    broker = FakeBroker(price=96.0)
    spy = _TrancheSpy(sold=False)
    positions = [{"symbol": "AAPL", "exchange": "NASD", "tranche_stage": 3}]
    check_positions_once(broker, positions, spy)
    assert broker.daily_calls == []
    assert spy.add_calls == []


def test_check_positions_no_add_when_stage_missing() -> None:
    # tranche_stage 미상이면 추가매수 점검 안 함(보수적)
    broker = FakeBroker(price=96.0)
    spy = _TrancheSpy(sold=False)
    check_positions_once(broker, [{"symbol": "AAPL", "exchange": "NASD"}], spy)
    assert broker.daily_calls == []
    assert spy.add_calls == []


def test_check_positions_add_survives_daily_error() -> None:
    # 일봉 조회 실패 → 그 종목만 스킵, 예외 없음
    broker = FakeBroker(price=96.0, fail_symbols={"AAPL"})
    spy = _TrancheSpy(sold=False)
    positions = [{"symbol": "AAPL", "exchange": "NASD", "tranche_stage": 1}]
    check_positions_once(broker, positions, spy)
    assert spy.add_calls == []  # 실패 → 추가매수 점검 못 함, 루프는 계속


def test_run_poll_loop_checks_positions_each_cycle() -> None:
    broker = FakeBroker(price=94.0)
    spy = _ExecutorSpy()
    run_poll_loop(
        broker, [("NAS", "AAPL")], interval=0, should_run=_counted_should_run(2),
        sleep=lambda _x: None, evaluator=lambda *a, **k: _entry(False), executor=spy,
        position_loader=lambda: [{"symbol": "AAPL", "exchange": "NASD"}],
    )
    assert len(spy.stop_calls) == 2  # 매 주기 포지션 점검
