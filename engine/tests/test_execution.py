"""실주문 실행(OrderExecutor) 테스트 — 최고 신중도.

기본 드라이런(실주문 0), LIVE+paper일 때만 실주문, 중복 방지, NAS→NASD 매핑,
주문 성공 후에만 기록, 기록 실패에도 루프 무중단 — 모든 경로를 mock으로 고정한다.
실네트워크 0.
"""

from __future__ import annotations

import logging

from worker.execution import OrderExecutor
from worker.indicators import (
    BollingerResult,
    EntryResult,
    MacdResult,
    PullbackResult,
    RsiResult,
    TrendResult,
)
from worker.orders import OrderConfig


def _entry() -> EntryResult:
    return EntryResult(
        enter=True,
        evaluable=True,
        trend=TrendResult(21.0, 20.0, 22.0, True, True),
        pullback=PullbackResult(100.0, 92.0, 0.08, True, True),
        rsi=RsiResult(31.0, True, True),
        bollinger=BollingerResult(10.0, 12.0, 8.0, 8.5, True, True),
        macd=MacdResult(-0.1, -0.2, 0.1, True, False),
        rebound_count=2,
        rebound_required=2,
    )


class FakeBroker:
    def __init__(self, order_no: str = "ODNO123") -> None:
        self.calls: list[tuple] = []
        self._order_no = order_no

    def place_overseas_order(self, exchange, symbol, quantity, side, price=None):
        self.calls.append((exchange, symbol, quantity, side, price))
        return {"order_no": self._order_no, "symbol": symbol, "exchange": exchange}


class FailBroker:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def place_overseas_order(self, *a, **k):
        self.calls.append(a)
        raise RuntimeError("KIS 주문 실패: rt_cd=1 msg=장 시작 전")


class _FakeTable:
    def __init__(self, db, name): self.db, self.name, self._rec = db, name, None
    def insert(self, rec): self._rec = rec; return self
    def upsert(self, rec): self._rec = rec; return self
    def update(self, rec): self._rec = rec; return self  # close_position용
    def eq(self, *a, **k): return self
    def execute(self):
        (self.db.orders if self.name == "orders" else self.db.positions).append(self._rec)
        return type("R", (), {"data": [self._rec]})()


class FakeDB:
    def __init__(self): self.orders, self.positions = [], []
    def table(self, name): return _FakeTable(self, name)


class RaisingDB:
    def table(self, name):
        raise RuntimeError("db down")


def _executor(broker, db=None, *, live, is_paper=True, held=None) -> OrderExecutor:
    return OrderExecutor(
        broker=broker,
        db_client=db,
        config=OrderConfig(total_capital=9000.0),
        live=live,
        is_paper=is_paper,
        held_symbols=held or set(),
        target_pct=0.08,
        stop_pct=0.05,
    )


def test_dryrun_default_no_real_order(caplog) -> None:
    broker = FakeBroker()
    ex = _executor(broker, live=False)
    with caplog.at_level(logging.INFO, logger="kestrel.engine"):
        ex.handle("NAS", "AAPL", 100.0, _entry())
    assert broker.calls == []  # 실주문 0
    assert any("드라이런" in m for m in caplog.messages)


def test_live_paper_places_and_records() -> None:
    broker, db = FakeBroker(), FakeDB()
    ex = _executor(broker, db, live=True)
    ex.handle("NAS", "AAPL", 100.0, _entry())
    assert len(broker.calls) == 1
    excd, symbol, qty, side, price = broker.calls[0]
    assert excd == "NASD" and symbol == "AAPL" and side == "buy"  # NAS→NASD 매핑
    assert len(db.orders) == 1 and db.orders[0]["broker_order_id"] == "ODNO123"
    assert db.orders[0]["order_type"] == "buy_1"
    assert len(db.positions) == 1
    pos = db.positions[0]
    assert pos["avg_price"] == price and pos["tranche_stage"] == 1 and pos["status"] == "open"
    assert pos["target_price"] == price * 1.08 and pos["stop_price"] == price * 0.95


def test_real_blocked_even_if_live() -> None:
    broker = FakeBroker()
    ex = _executor(broker, FakeDB(), live=True, is_paper=False)  # real
    ex.handle("NAS", "AAPL", 100.0, _entry())
    assert broker.calls == []  # 실전이면 LIVE여도 실주문 차단


def test_skips_when_already_held() -> None:
    broker = FakeBroker()
    ex = _executor(broker, FakeDB(), live=True, held={"AAPL"})
    ex.handle("NAS", "AAPL", 100.0, _entry())
    assert broker.calls == []  # 이미 보유 → 주문 0


def test_no_duplicate_within_session() -> None:
    broker, db = FakeBroker(), FakeDB()
    ex = _executor(broker, db, live=True)
    ex.handle("NAS", "AAPL", 100.0, _entry())
    ex.handle("NAS", "AAPL", 100.0, _entry())  # 같은 종목 재신호
    assert len(broker.calls) == 1  # 한 번만 발주


def test_order_failure_no_position(caplog) -> None:
    broker, db = FailBroker(), FakeDB()
    ex = _executor(broker, db, live=True)
    with caplog.at_level(logging.WARNING, logger="kestrel.engine"):
        ex.handle("NAS", "AAPL", 100.0, _entry())  # 예외 전파 안 함
    assert len(db.positions) == 0  # 주문 실패 → 포지션 미생성
    assert any("실패" in m for m in caplog.messages)


def test_db_failure_does_not_raise(caplog) -> None:
    broker = FakeBroker()
    ex = _executor(broker, RaisingDB(), live=True)
    with caplog.at_level(logging.WARNING, logger="kestrel.engine"):
        ex.handle("NAS", "AAPL", 100.0, _entry())  # 주문은 나갔고 기록만 실패
    assert len(broker.calls) == 1  # 주문은 성공
    assert any("기록 실패" in m for m in caplog.messages)


def test_skip_logs_reason_no_order(caplog) -> None:
    # 진입 신호지만 결정이 생략(보유 한도)이면 주문 0
    broker = FakeBroker()
    ex = _executor(broker, FakeDB(), live=True, held={"A", "B", "C"})
    ex.handle("NAS", "AAPL", 100.0, _entry())
    assert broker.calls == []


# --- 손절 매도 ------------------------------------------------------------

def _position(avg=100.0, stop=95.0, qty=10) -> dict:
    return {"symbol": "AAPL", "exchange": "NASD", "avg_price": avg, "stop_price": stop, "quantity": qty}


def test_stop_loss_dryrun_no_real_sell(caplog) -> None:
    broker = FakeBroker()
    ex = _executor(broker, FakeDB(), live=False)
    with caplog.at_level(logging.INFO, logger="kestrel.engine"):
        ex.handle_stop_loss(_position(), current_price=90.0)  # 손절가 아래
    assert broker.calls == []  # 드라이런 → 실매도 0
    assert any("손절 예정(드라이런)" in m for m in caplog.messages)


def test_stop_loss_live_sells_and_closes() -> None:
    broker, db = FakeBroker(order_no="SELL1"), FakeDB()
    ex = _executor(broker, db, live=True)
    ex.handle_stop_loss(_position(avg=100.0, stop=95.0, qty=10), current_price=94.0)
    assert len(broker.calls) == 1
    excd, symbol, qty, side, price = broker.calls[0]
    assert excd == "NASD" and side == "sell" and qty == 10  # 포지션 거래소코드 그대로(NASD)
    assert len(db.orders) == 1
    o = db.orders[0]
    assert o["side"] == "sell" and o["order_type"] == "sell_sl"
    assert o["realized_pnl"] == (94.0 - 100.0) * 10  # -60
    assert len(db.positions) == 1 and db.positions[0]["status"] == "closed"


def test_stop_loss_no_sell_when_not_triggered() -> None:
    broker = FakeBroker()
    ex = _executor(broker, FakeDB(), live=True)
    ex.handle_stop_loss(_position(stop=95.0), current_price=98.0)  # 미도달
    assert broker.calls == []


def test_stop_loss_real_blocked() -> None:
    broker = FakeBroker()
    ex = _executor(broker, FakeDB(), live=True, is_paper=False)
    ex.handle_stop_loss(_position(), current_price=90.0)
    assert broker.calls == []  # 실전이면 매도도 차단


def test_stop_loss_no_duplicate_sell() -> None:
    broker, db = FakeBroker(), FakeDB()
    ex = _executor(broker, db, live=True)
    ex.handle_stop_loss(_position(), current_price=90.0)
    ex.handle_stop_loss(_position(), current_price=90.0)  # 재점검
    assert len(broker.calls) == 1  # 한 번만 매도


def test_stop_loss_failure_keeps_position(caplog) -> None:
    broker, db = FailBroker(), FakeDB()
    ex = _executor(broker, db, live=True)
    with caplog.at_level(logging.WARNING, logger="kestrel.engine"):
        ex.handle_stop_loss(_position(), current_price=90.0)  # 예외 전파 안 함
    assert db.positions == []  # 매도 실패 → 청산 안 됨(포지션 유지)
    assert any("손절 매도 실패" in m for m in caplog.messages)


# --- 익절 매도 (손절과 대칭) ----------------------------------------------

def _position_tp(avg=100.0, target=108.0, qty=10) -> dict:
    return {"symbol": "AAPL", "exchange": "NASD", "avg_price": avg, "target_price": target, "quantity": qty}


def test_take_profit_dryrun_no_real_sell(caplog) -> None:
    broker = FakeBroker()
    ex = _executor(broker, FakeDB(), live=False)
    with caplog.at_level(logging.INFO, logger="kestrel.engine"):
        ex.handle_take_profit(_position_tp(), current_price=110.0)  # 목표가 위
    assert broker.calls == []
    assert any("익절 예정(드라이런)" in m for m in caplog.messages)


def test_take_profit_live_sells_and_closes() -> None:
    broker, db = FakeBroker(order_no="TP1"), FakeDB()
    ex = _executor(broker, db, live=True)
    ex.handle_take_profit(_position_tp(avg=100.0, target=108.0, qty=10), current_price=109.0)
    assert len(broker.calls) == 1 and broker.calls[0][3] == "sell"
    assert db.orders[0]["order_type"] == "sell_tp"
    assert db.orders[0]["realized_pnl"] == (109.0 - 100.0) * 10  # +90
    assert db.positions[0]["status"] == "closed"


def test_take_profit_real_blocked() -> None:
    broker = FakeBroker()
    ex = _executor(broker, FakeDB(), live=True, is_paper=False)
    ex.handle_take_profit(_position_tp(), current_price=110.0)
    assert broker.calls == []


def test_handle_position_sells_only_once_when_both_trigger() -> None:
    # 방어적: 손절·익절이 동시에 참이어도 한 번만 매도(손절 우선)
    broker, db = FakeBroker(), FakeDB()
    ex = _executor(broker, db, live=True)
    pos = {"symbol": "AAPL", "exchange": "NASD", "avg_price": 100.0,
           "stop_price": 95.0, "target_price": 108.0, "quantity": 10}
    ex.handle_position(pos, current_price=200.0)  # target 위(익절 참) & 손절 거짓 → 익절 1회
    assert len(broker.calls) == 1
    assert db.orders[0]["order_type"] == "sell_tp"


def test_handle_position_take_profit_when_not_stopped() -> None:
    broker, db = FakeBroker(), FakeDB()
    ex = _executor(broker, db, live=True)
    pos = {"symbol": "AAPL", "exchange": "NASD", "avg_price": 100.0,
           "stop_price": 95.0, "target_price": 108.0, "quantity": 10}
    ex.handle_position(pos, current_price=109.0)  # 손절 미도달·익절 도달
    assert len(broker.calls) == 1 and db.orders[0]["order_type"] == "sell_tp"


def test_handle_position_returns_whether_exit_attempted() -> None:
    # 청산 우선순위의 근거: 청산(시도)이면 True — 호출부는 True면 추가매수를 점검하지 않는다.
    # 드라이런에서도 손절 트리거면 True(드라이런이라고 추가매수로 새면 물타기).
    ex = _executor(FakeBroker(), FakeDB(), live=False)
    pos = {"symbol": "AAPL", "exchange": "NASD", "avg_price": 100.0,
           "stop_price": 95.0, "target_price": 108.0, "quantity": 10}
    assert ex.handle_position(pos, current_price=94.0) is True   # 손절 트리거(드라이런)
    assert ex.handle_position(pos, current_price=109.0) is True  # 익절 트리거
    assert ex.handle_position(pos, current_price=100.0) is False  # 아무 청산도 없음


# --- 분할 2·3차 매수 실행 ----------------------------------------------------

def _rebound_entry(count: int = 2) -> EntryResult:
    return EntryResult(
        enter=False,
        evaluable=True,
        trend=TrendResult(21.0, 20.0, 22.0, True, True),
        pullback=PullbackResult(100.0, 92.0, 0.08, True, True),
        rsi=RsiResult(31.0, True, count >= 1),
        bollinger=BollingerResult(10.0, 12.0, 8.0, 8.5, True, count >= 2),
        macd=MacdResult(-0.1, -0.2, 0.1, True, count >= 3),
        rebound_count=count,
        rebound_required=2,
    )


def _position_add(avg=100.0, stop=95.0, qty=12, stage=1) -> dict:
    return {
        "symbol": "AAPL", "exchange": "NASD", "avg_price": avg,
        "stop_price": stop, "target_price": avg * 1.08, "quantity": qty,
        "tranche_stage": stage, "status": "open",
    }


def test_add_tranche_dryrun_no_real_order(caplog) -> None:
    broker = FakeBroker()
    ex = _executor(broker, FakeDB(), live=False)
    with caplog.at_level(logging.INFO, logger="kestrel.engine"):
        ex.handle_add_tranche(_position_add(), 97.0, _rebound_entry(2))
    assert broker.calls == []  # 실주문 0
    assert any("드라이런" in m for m in caplog.messages)


def test_add_tranche_live_paper_places_and_updates_position() -> None:
    broker, db = FakeBroker(order_no="ADD2"), FakeDB()
    ex = _executor(broker, db, live=True)
    ex.handle_add_tranche(_position_add(avg=100.0, stop=95.0, qty=12, stage=1), 97.0, _rebound_entry(2))
    # 주문: 포지션 거래소 코드(NASD) 그대로, 900//97 = 9주 매수
    assert broker.calls == [("NASD", "AAPL", 9, "buy", 97.0)]
    assert len(db.orders) == 1
    o = db.orders[0]
    assert o["order_type"] == "buy_2" and o["side"] == "buy" and o["broker_order_id"] == "ADD2"
    # 포지션 갱신: 평단 가중평균, 수량 합산, 단계 2
    assert len(db.positions) == 1
    pos = db.positions[0]
    new_avg = (100.0 * 12 + 97.0 * 9) / 21
    assert pos["avg_price"] == new_avg
    assert pos["quantity"] == 21
    assert pos["tranche_stage"] == 2
    assert pos["stop_price"] == 95.0  # 손절가는 1차 값 유지(재계산 금지 — 물타기 방지)
    assert pos["target_price"] == new_avg * 1.08  # 목표가는 새 평단 기준 재계산
    assert pos["status"] == "open"


def test_add_tranche_stage3_order_type() -> None:
    broker, db = FakeBroker(), FakeDB()
    ex = _executor(broker, db, live=True)
    ex.handle_add_tranche(_position_add(avg=99.0, stage=2), 96.0, _rebound_entry(2))
    assert db.orders[0]["order_type"] == "buy_3"
    assert db.positions[0]["tranche_stage"] == 3


def test_add_tranche_real_blocked_even_if_live() -> None:
    broker = FakeBroker()
    ex = _executor(broker, FakeDB(), live=True, is_paper=False)  # real
    ex.handle_add_tranche(_position_add(), 97.0, _rebound_entry(2))
    assert broker.calls == []  # 실전이면 LIVE여도 차단


def test_add_tranche_no_duplicate_same_stage_within_session() -> None:
    broker, db = FakeBroker(), FakeDB()
    ex = _executor(broker, db, live=True)
    pos = _position_add(stage=1)
    ex.handle_add_tranche(pos, 97.0, _rebound_entry(2))
    ex.handle_add_tranche(pos, 97.0, _rebound_entry(2))  # DB 미반영 등으로 같은 stage 재점검
    assert len(broker.calls) == 1  # 같은 차수는 세션 내 한 번만


def test_add_tranche_not_ordered_no_broker_call(caplog) -> None:
    # 판정에서 생략(하락 미달)이면 주문 자체가 없다
    broker = FakeBroker()
    ex = _executor(broker, FakeDB(), live=True)
    with caplog.at_level(logging.INFO, logger="kestrel.engine"):
        ex.handle_add_tranche(_position_add(), 99.0, _rebound_entry(3))
    assert broker.calls == []
    assert any("추가매수 안 함" in m for m in caplog.messages)


def test_add_tranche_below_stop_no_buy() -> None:
    # 물타기 방지: 손절선 이하에서는 executor 경로에서도 매수 0
    broker = FakeBroker()
    ex = _executor(broker, FakeDB(), live=True)
    ex.handle_add_tranche(_position_add(stop=95.0), 94.0, _rebound_entry(3))
    assert broker.calls == []


def test_add_tranche_order_failure_keeps_position(caplog) -> None:
    broker, db = FailBroker(), FakeDB()
    ex = _executor(broker, db, live=True)
    with caplog.at_level(logging.WARNING, logger="kestrel.engine"):
        ex.handle_add_tranche(_position_add(), 97.0, _rebound_entry(2))  # 예외 전파 안 함
    assert db.positions == []  # 주문 실패 → 포지션 갱신 없음
    assert len(db.orders) == 1 and db.orders[0]["status"] == "rejected"  # 실패 기록
    assert any("실패" in m for m in caplog.messages)


def test_add_tranche_db_failure_does_not_raise(caplog) -> None:
    broker = FakeBroker()
    ex = _executor(broker, RaisingDB(), live=True)
    with caplog.at_level(logging.WARNING, logger="kestrel.engine"):
        ex.handle_add_tranche(_position_add(), 97.0, _rebound_entry(2))  # 기록만 실패
    assert len(broker.calls) == 1  # 주문은 성공
    assert any("기록 실패" in m for m in caplog.messages)
