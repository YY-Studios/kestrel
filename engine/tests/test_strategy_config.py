"""전략설정 검증/매핑 테스트 — DB에서 읽은 값의 범위 재검증·폴백·evaluate_entry 매핑.

engine은 api를 import하지 않으므로(패키지 경계) 범위·기본값을 자체 보유한다. 이 테스트가
그 값이 전략 코드 기본값과 일치하는지, DB 이상값을 안전하게 걸러내는지를 고정한다. 실네트워크 0.
"""

from __future__ import annotations

from worker import indicators
from worker.orders import ORDER_MAX_POSITIONS
from worker.strategy_config import (
    DEFAULTS,
    RANGES,
    evaluate_overrides,
    validate_strategy_settings,
)


# --- 기본값이 전략 코드 기본값과 일치 --------------------------------------

def test_defaults_match_strategy_code() -> None:
    assert DEFAULTS["rsi_threshold"] == indicators.RSI_OVERSOLD
    assert DEFAULTS["pullback_min"] == indicators.PULLBACK_MIN_DROP
    assert DEFAULTS["pullback_max"] == indicators.PULLBACK_MAX_DROP
    assert DEFAULTS["rebound_required"] == indicators.REBOUND_REQUIRED
    assert DEFAULTS["take_profit_pct"] == 0.08  # OrderExecutor target_pct 기본
    assert DEFAULTS["stop_loss_pct"] == 0.05    # OrderExecutor stop_pct 기본
    assert DEFAULTS["max_positions"] == ORDER_MAX_POSITIONS


def test_every_default_is_within_range() -> None:
    for key, (lo, hi, _is_int) in RANGES.items():
        assert lo <= DEFAULTS[key] <= hi, key


# --- validate_strategy_settings: 폴백/범위/형변환 -------------------------

def test_none_row_returns_all_defaults() -> None:
    assert validate_strategy_settings(None) == DEFAULTS
    assert validate_strategy_settings({}) == DEFAULTS


def test_valid_row_applied() -> None:
    row = {
        "rsi_threshold": 30, "pullback_min": 0.03, "pullback_max": 0.12,
        "rebound_required": 1, "take_profit_pct": 0.10, "stop_loss_pct": 0.03,
        "total_capital": 5000, "max_positions": 2,
    }
    out = validate_strategy_settings(row)
    assert out["rsi_threshold"] == 30 and out["rebound_required"] == 1
    assert out["take_profit_pct"] == 0.10 and out["stop_loss_pct"] == 0.03
    assert out["total_capital"] == 5000 and out["max_positions"] == 2


def test_out_of_range_field_falls_back_to_default() -> None:
    # DB에 직접 넣은 이상값은 쓰지 않고 그 필드만 기본값으로
    row = {"rsi_threshold": 99, "stop_loss_pct": 0.9, "rebound_required": 0}
    out = validate_strategy_settings(row)
    assert out["rsi_threshold"] == DEFAULTS["rsi_threshold"]
    assert out["stop_loss_pct"] == DEFAULTS["stop_loss_pct"]
    assert out["rebound_required"] == DEFAULTS["rebound_required"]


def test_missing_and_null_fields_use_defaults() -> None:
    out = validate_strategy_settings({"rsi_threshold": 40, "pullback_min": None})
    assert out["rsi_threshold"] == 40                       # 제공값
    assert out["pullback_min"] == DEFAULTS["pullback_min"]  # null → 기본
    assert out["take_profit_pct"] == DEFAULTS["take_profit_pct"]  # 누락 → 기본


def test_non_numeric_field_falls_back() -> None:
    out = validate_strategy_settings({"rsi_threshold": "abc"})
    assert out["rsi_threshold"] == DEFAULTS["rsi_threshold"]


def test_int_fields_are_int() -> None:
    out = validate_strategy_settings({"rebound_required": 3, "max_positions": 2})
    assert out["rebound_required"] == 3 and isinstance(out["rebound_required"], int)
    assert isinstance(out["max_positions"], int)


def test_pullback_min_gt_max_resets_both() -> None:
    out = validate_strategy_settings({"pullback_min": 0.10, "pullback_max": 0.06})
    assert out["pullback_min"] == DEFAULTS["pullback_min"]
    assert out["pullback_max"] == DEFAULTS["pullback_max"]


def test_bool_is_rejected_as_non_numeric() -> None:
    # bool이 int(1/0)로 새지 않게
    out = validate_strategy_settings({"rebound_required": True})
    assert out["rebound_required"] == DEFAULTS["rebound_required"]


# --- evaluate_entry 매핑 ---------------------------------------------------

def test_evaluate_overrides_maps_to_evaluate_entry_kwargs() -> None:
    strat = validate_strategy_settings(
        {"rsi_threshold": 30, "pullback_min": 0.03, "pullback_max": 0.12, "rebound_required": 1}
    )
    ov = evaluate_overrides(strat)
    assert ov == {
        "rsi_threshold": 30,
        "pullback_min_drop": 0.03,
        "pullback_max_drop": 0.12,
        "rebound_required": 1,
    }
