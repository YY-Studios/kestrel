"""진입 주문 결정(드라이런) 테스트.

순수 로직 — 외부 호출 0, 실주문 0. 수량 계산·배분·보유 제한만 검증한다.
"""

from __future__ import annotations

import pytest

from worker.indicators import (
    BollingerResult,
    EntryResult,
    MacdResult,
    PullbackResult,
    RsiResult,
    TrendResult,
)
from worker.orders import (
    OrderConfig,
    decide_add_tranche,
    decide_buy_order,
    decide_stop_loss,
    decide_take_profit,
    format_order_decision,
    merge_tranche_fill,
)


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


# --- 익절 판정 (손절과 대칭) -----------------------------------------------

def _pos_tp(avg=100.0, target=108.0, qty=10) -> dict:
    return {"symbol": "AAPL", "exchange": "NASD", "avg_price": avg, "target_price": target, "quantity": qty}


def test_take_profit_triggers_at_or_above_target() -> None:
    d = decide_take_profit(_pos_tp(avg=100.0, target=108.0, qty=10), current_price=108.0)  # 정확히 목표가
    assert d.should_sell is True
    assert d.realized_pnl == (108.0 - 100.0) * 10  # +80
    assert decide_take_profit(_pos_tp(), current_price=110.0).should_sell is True  # 위로


def test_take_profit_not_triggered_below_target() -> None:
    assert decide_take_profit(_pos_tp(target=108.0), current_price=105.0).should_sell is False


def test_take_profit_insufficient_data_no_sell() -> None:
    assert decide_take_profit(_pos_tp(), current_price=None).should_sell is False
    assert decide_take_profit({"symbol": "AAPL", "quantity": 10}, current_price=110.0).should_sell is False


# --- 분할 2·3차 매수 판정 (물타기와 구분) ------------------------------------

def _rebound_entry(count: int, required: int = 2) -> EntryResult:
    """반등 신호 count/3 상태의 EntryResult (추가매수 판정은 반등 유지만 본다)."""
    return EntryResult(
        enter=False,
        evaluable=True,
        trend=TrendResult(21.0, 20.0, 22.0, True, True),
        pullback=PullbackResult(100.0, 92.0, 0.08, True, True),
        rsi=RsiResult(31.0, True, count >= 1),
        bollinger=BollingerResult(10.0, 12.0, 8.0, 8.5, True, count >= 2),
        macd=MacdResult(-0.1, -0.2, 0.1, True, count >= 3),
        rebound_count=count,
        rebound_required=required,
    )


def _held_pos(avg=100.0, stop=95.0, qty=12, stage=1) -> dict:
    return {
        "symbol": "AAPL", "exchange": "NASD", "avg_price": avg,
        "stop_price": stop, "target_price": 108.0, "quantity": qty, "tranche_stage": stage,
    }


def test_add_tranche_stage2_when_all_conditions_met() -> None:
    # 평단 100, 현재가 97 = 정확히 -3%(경계 포함), 손절선(95) 위, 반등 2/3 유지 → 2차 매수
    # 배분 = 9000/3 = 3000, 2차 = 3000*0.3 = 900, 900//97 = 9주
    d = decide_add_tranche(_held_pos(), 97.0, _rebound_entry(2), config=_cfg())
    assert d.ordered is True
    assert d.tranche_stage == 2
    assert d.quantity == 9
    assert d.limit_price == 97.0
    assert d.side == "buy"
    assert d.tranche_pct == 0.30
    assert d.tranche_amount == 900.0


def test_add_tranche_stage3_after_stage2() -> None:
    # 2차까지 산 포지션(평단 99) → 조건 충족 시 3차
    d = decide_add_tranche(_held_pos(avg=99.0, stage=2), 96.0, _rebound_entry(3), config=_cfg())
    assert d.ordered is True
    assert d.tranche_stage == 3


def test_add_tranche_blocked_at_or_below_stop() -> None:
    # 핵심(물타기 방지): 손절선 도달·이하면 하락·반등이 충족돼도 절대 추가매수 안 함
    d = decide_add_tranche(_held_pos(stop=95.0), 95.0, _rebound_entry(3), config=_cfg())  # 정확히 손절가
    assert d.ordered is False
    assert "손절" in d.reason
    d2 = decide_add_tranche(_held_pos(stop=95.0), 90.0, _rebound_entry(3), config=_cfg())  # 아래
    assert d2.ordered is False
    assert "손절" in d2.reason


def test_add_tranche_requires_additional_drop() -> None:
    # 평단 대비 -3% 미달(-1%)이면 추가매수 안 함
    d = decide_add_tranche(_held_pos(), 99.0, _rebound_entry(3), config=_cfg())
    assert d.ordered is False
    assert "하락" in d.reason


def test_add_tranche_requires_rebound_maintained() -> None:
    # 반등 신호 1/3로 죽었으면 추가매수 안 함
    d = decide_add_tranche(_held_pos(), 97.0, _rebound_entry(1), config=_cfg())
    assert d.ordered is False
    assert "반등" in d.reason


def test_add_tranche_no_entry_result_no_buy() -> None:
    d = decide_add_tranche(_held_pos(), 97.0, None, config=_cfg())
    assert d.ordered is False


def test_add_tranche_done_after_stage3() -> None:
    d = decide_add_tranche(_held_pos(stage=3), 97.0, _rebound_entry(3), config=_cfg())
    assert d.ordered is False
    assert "완료" in d.reason


def test_add_tranche_insufficient_data_no_buy() -> None:
    # 현재가/손절가/평단/단계 없음 → 판단 불가, 매수 안 함
    assert decide_add_tranche(_held_pos(), None, _rebound_entry(3), config=_cfg()).ordered is False
    no_stop = {k: v for k, v in _held_pos().items() if k != "stop_price"}
    assert decide_add_tranche(no_stop, 97.0, _rebound_entry(3), config=_cfg()).ordered is False
    no_avg = {k: v for k, v in _held_pos().items() if k != "avg_price"}
    assert decide_add_tranche(no_avg, 97.0, _rebound_entry(3), config=_cfg()).ordered is False
    no_stage = {k: v for k, v in _held_pos().items() if k != "tranche_stage"}
    assert decide_add_tranche(no_stage, 97.0, _rebound_entry(3), config=_cfg()).ordered is False


def test_add_tranche_quantity_zero_no_buy() -> None:
    # 2차 금액(90*0.3/3=9)으로 1주도 못 사면 생략
    cfg = _cfg(total=90.0)
    d = decide_add_tranche(_held_pos(), 97.0, _rebound_entry(3), config=cfg)
    assert d.ordered is False
    assert "수량" in d.reason


# --- 평단 재계산(가중평균) ----------------------------------------------------

def test_merge_tranche_fill_weighted_average() -> None:
    # (100×12 + 97×9) / 21 = 2073/21
    new_avg, total_qty = merge_tranche_fill(100.0, 12, 97.0, 9)
    assert total_qty == 21
    assert new_avg == pytest.approx(2073.0 / 21.0)


def test_merge_tranche_fill_same_price_keeps_avg() -> None:
    new_avg, total_qty = merge_tranche_fill(100.0, 10, 100.0, 5)
    assert new_avg == pytest.approx(100.0)
    assert total_qty == 15
