"""시세 폴링 루프 테스트 (engine 첫 슬라이스).

broker를 가짜로 주입해 실네트워크 없이 검증한다.
무한 루프는 should_run/ sleep 주입으로 "몇 회 돌고 멈추게" 한다.
"""

from __future__ import annotations

from worker.loop import parse_watchlist, poll_once, run_poll_loop


class FakeClient:
    """get_overseas_price만 흉내내는 가짜 broker. fail_symbols는 예외를 던진다."""

    def __init__(self, fail_symbols: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail = fail_symbols or set()

    def get_overseas_price(self, exchange: str, symbol: str) -> dict:
        self.calls.append((exchange, symbol))
        if symbol in self._fail:
            raise RuntimeError("일시적 시세 오류")
        return {"symbol": symbol, "exchange": exchange, "price": 123.45, "raw": {}}


def _counted_should_run(n: int):
    state = {"i": 0}

    def should_run() -> bool:
        state["i"] += 1
        return state["i"] <= n

    return should_run


def test_parse_watchlist() -> None:
    assert parse_watchlist(["NAS:AAPL", "NYS:IBM"]) == [("NAS", "AAPL"), ("NYS", "IBM")]
    # 빈 항목·형식 오류는 무시, 소문자는 대문자로
    assert parse_watchlist(["", "nas:tsla", "garbage"]) == [("NAS", "TSLA")]


def test_poll_once_calls_each_symbol() -> None:
    client = FakeClient()
    poll_once(client, [("NAS", "AAPL"), ("NAS", "TSLA")])
    assert client.calls == [("NAS", "AAPL"), ("NAS", "TSLA")]


def test_poll_once_continues_on_error() -> None:
    # 한 종목 조회가 실패해도 다음 종목은 계속 조회한다(루프가 죽지 않음).
    client = FakeClient(fail_symbols={"AAPL"})
    poll_once(client, [("NAS", "AAPL"), ("NAS", "TSLA")])
    assert ("NAS", "TSLA") in client.calls


def test_run_poll_loop_stops_when_should_run_false() -> None:
    client = FakeClient()
    slept: list[float] = []
    run_poll_loop(
        client, [("NAS", "AAPL")], interval=5, should_run=_counted_should_run(3), sleep=slept.append
    )
    assert len(client.calls) == 3  # 3주기 돌고 멈춤
    assert slept == [5, 5, 5]


def test_run_poll_loop_survives_price_errors() -> None:
    # 매 주기 조회가 실패해도 루프 자체는 should_run이 멈출 때까지 계속 돈다.
    client = FakeClient(fail_symbols={"AAPL"})
    run_poll_loop(
        client, [("NAS", "AAPL")], interval=0, should_run=_counted_should_run(2), sleep=lambda _x: None
    )
    assert len(client.calls) == 2
