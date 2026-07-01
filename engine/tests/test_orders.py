"""진입 주문 결정(드라이런) 테스트.

순수 로직 — 외부 호출 0, 실주문 0. 수량 계산·배분·보유 제한만 검증한다.
"""

from __future__ import annotations

from worker.orders import OrderConfig, decide_buy_order, decide_stop_loss, format_order_decision


def _cfg(total=9000.0, max_positions=3, first=0.40) -> OrderConfig:
    return OrderConfig(total_capital=total, max_positions=max_positions, first_tranche_pct=first)


def test_decide_quantity_floor() -> None:
    # 배분 = 9000/3 = 3000, 1차 = 3000*0.4 = 1200, 현재가 100 → 12주
    d = decide_buy_order("NASD", "AAPL", 100.0, held_symbols=set(), config=_cfg())
    assert d.ordered is True
    assert d.quantity == 12
    assert d.allocation == 3000.0
    assert d.tranche_amount == 1200.0
    assert d.limit_price == 100.0
    assert d.side == "buy"


def test_decide_quantity_rounds_down() -> None:
    # 1200 / 290 = 4.13 → 4주(내림)
    d = decide_buy_order("NASD", "AAPL", 290.0, held_symbols=set(), config=_cfg())
    assert d.quantity == 4


def test_decide_skips_when_already_held() -> None:
    d = decide_buy_order("NASD", "AAPL", 100.0, held_symbols={"AAPL"}, config=_cfg())
    assert d.ordered is False
    assert "보유" in d.reason


def test_decide_skips_when_at_position_limit() -> None:
    d = decide_buy_order("NASD", "NVDA", 100.0, held_symbols={"AAPL", "TSLA", "MSFT"}, config=_cfg())
    assert d.ordered is False
    assert "한도" in d.reason


def test_decide_skips_when_quantity_zero() -> None:
    # 현재가가 1차 금액(1200)보다 비싸면 0주 → 생략
    d = decide_buy_order("NASD", "BRKA", 5000.0, held_symbols=set(), config=_cfg())
    assert d.ordered is False
    assert d.quantity == 0
    assert "수량" in d.reason


def test_decide_skips_when_no_price() -> None:
    d = decide_buy_order("NASD", "AAPL", None, held_symbols=set(), config=_cfg())
    assert d.ordered is False


def test_format_order_decision_ordered_marks_dryrun() -> None:
    d = decide_buy_order("NASD", "AAPL", 100.0, held_symbols=set(), config=_cfg())
    s = format_order_decision(d)
    assert "드라이런" in s and "AAPL" in s and "12주" in s


def test_format_order_decision_skip_shows_reason() -> None:
    d = decide_buy_order("NASD", "AAPL", 100.0, held_symbols={"AAPL"}, config=_cfg())
    s = format_order_decision(d)
    assert "주문 안 함" in s and "보유" in s


# --- 손절 판정 -------------------------------------------------------------

def _pos(avg=100.0, stop=95.0, qty=10) -> dict:
    return {"symbol": "AAPL", "exchange": "NASD", "avg_price": avg, "stop_price": stop, "quantity": qty}


def test_stop_loss_triggers_at_or_below_stop() -> None:
    d = decide_stop_loss(_pos(avg=100.0, stop=95.0, qty=10), current_price=95.0)  # 정확히 손절가
    assert d.should_sell is True
    assert d.realized_pnl == (95.0 - 100.0) * 10  # -50
    d2 = decide_stop_loss(_pos(), current_price=90.0)  # 아래로
    assert d2.should_sell is True


def test_stop_loss_not_triggered_above_stop() -> None:
    d = decide_stop_loss(_pos(avg=100.0, stop=95.0), current_price=97.0)
    assert d.should_sell is False


def test_stop_loss_insufficient_data_no_sell() -> None:
    assert decide_stop_loss(_pos(), current_price=None).should_sell is False
    assert decide_stop_loss({"symbol": "AAPL", "quantity": 10}, current_price=90.0).should_sell is False
