"""검증용 완화 프로필 테스트 — env 오버라이드가 임계값을 올바로 덮는지, 미설정 시 기본인지.

실네트워크 0. env는 dict로 직접 주입(os.environ 오염 없음).
핵심: 평상시(빈 env)엔 영향 0(오버라이드 없음 → evaluate_entry 기본), 검증 시에만 완화.
"""

from __future__ import annotations

from worker.entry_profile import (
    PRESET_VERIFY,
    build_evaluator,
    describe,
    load_overrides,
    profile_active,
)
from worker.indicators import evaluate_entry


# --- load_overrides: 미설정 시 기본(빈 dict) --------------------------------

def test_no_env_means_no_overrides() -> None:
    assert load_overrides({}) == {}
    assert profile_active({}) is False


def test_blank_values_are_ignored() -> None:
    # 빈 문자열/공백은 미설정과 동일 취급 → 기본값 유지
    env = {"ENTRY_TREND_BYPASS": "", "ENTRY_REBOUND_REQUIRED": "   ", "ENTRY_PROFILE": ""}
    assert load_overrides(env) == {}
    assert profile_active(env) is False


# --- ENTRY_PROFILE=verify 프리셋 -------------------------------------------

def test_verify_preset_applies_full_bundle() -> None:
    env = {"ENTRY_PROFILE": "verify"}
    assert load_overrides(env) == PRESET_VERIFY
    assert profile_active(env) is True


def test_verify_preset_is_case_insensitive() -> None:
    assert load_overrides({"ENTRY_PROFILE": "VERIFY"}) == PRESET_VERIFY


def test_unknown_profile_name_does_nothing() -> None:
    assert load_overrides({"ENTRY_PROFILE": "prod"}) == {}


# --- 개별 env 오버라이드 ----------------------------------------------------

def test_individual_overrides_parsed_by_type() -> None:
    env = {
        "ENTRY_TREND_BYPASS": "true",
        "ENTRY_REBOUND_REQUIRED": "1",
        "ENTRY_PULLBACK_MIN_DROP": "0.0",
        "ENTRY_PULLBACK_MAX_DROP": "0.5",
        "ENTRY_RSI_THRESHOLD": "80",
    }
    assert load_overrides(env) == {
        "trend_bypass": True,
        "rebound_required": 1,
        "pullback_min_drop": 0.0,
        "pullback_max_drop": 0.5,
        "rsi_threshold": 80.0,
    }


def test_individual_override_beats_preset() -> None:
    # 개별 env가 프리셋 위에 덮인다(개별 우선).
    env = {"ENTRY_PROFILE": "verify", "ENTRY_REBOUND_REQUIRED": "2"}
    overrides = load_overrides(env)
    assert overrides["rebound_required"] == 2  # 프리셋의 1을 덮음
    assert overrides["trend_bypass"] is True   # 나머지는 프리셋 유지


def test_individual_bool_false_can_disable_preset_bypass() -> None:
    env = {"ENTRY_PROFILE": "verify", "ENTRY_TREND_BYPASS": "false"}
    assert load_overrides(env)["trend_bypass"] is False


# --- describe (로그용) ------------------------------------------------------

def test_describe_lists_active_overrides() -> None:
    text = describe({"ENTRY_TREND_BYPASS": "true"})
    assert "trend_bypass=True" in text


def test_describe_empty_when_no_overrides() -> None:
    assert describe({}) == "(없음)"


# --- build_evaluator: 완화 없으면 그대로, 있으면 완화 적용 -------------------

def _downtrend_closes(n: int = 70) -> list[float]:
    """추세가 확실히 실패하는(하락) 종가. 데이터는 충분(>=60)해 evaluable=True."""
    return [100.0 - i for i in range(n)]


def test_build_evaluator_without_env_is_plain_evaluate_entry() -> None:
    assert build_evaluator({}) is evaluate_entry


def test_build_evaluator_applies_base_overrides() -> None:
    # DB 설정을 base_overrides로 주입 — evaluate_entry에 그 임계값이 실린다.
    import functools

    ev = build_evaluator({}, base_overrides={"rsi_threshold": 30, "rebound_required": 1})
    assert isinstance(ev, functools.partial)
    assert ev.keywords["rsi_threshold"] == 30 and ev.keywords["rebound_required"] == 1


def test_env_overrides_win_over_base_overrides() -> None:
    # 검증 완화 env가 DB 설정(base) 위에 우선한다(우선순위 규칙).
    ev = build_evaluator(
        {"ENTRY_REBOUND_REQUIRED": "3"}, base_overrides={"rebound_required": 1, "rsi_threshold": 30}
    )
    assert ev.keywords["rebound_required"] == 3   # env 우선
    assert ev.keywords["rsi_threshold"] == 30     # env에 없으면 base 유지


def test_build_evaluator_none_base_no_env_is_plain() -> None:
    assert build_evaluator({}, base_overrides=None) is evaluate_entry


def test_default_evaluator_does_not_enter_on_downtrend() -> None:
    closes = _downtrend_closes()
    result = build_evaluator({})(closes, current_price=closes[-1])
    assert result.evaluable is True
    assert result.enter is False  # 추세 미통과 → 진입 안 함(평상시 동작)


def test_verify_profile_reaches_entry_on_same_data() -> None:
    # 같은 하락 데이터라도 검증 프로필이면 진입 신호까지 도달해야 한다.
    closes = _downtrend_closes()
    result = build_evaluator({"ENTRY_PROFILE": "verify"})(closes, current_price=closes[-1])
    assert result.enter is True
    # 완화지만 근거(추세 실제 상태)는 훼손하지 않는다 — 추세는 실제로 미통과.
    assert result.trend.passed is False
