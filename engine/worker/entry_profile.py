"""검증용 진입 완화 프로필 — env로만 완화, 미설정 시 전략 기본값 그대로.

LIVE 진입 매수가 실제 KIS paper 계좌로 나가는지 통제된 상태에서 한 번 확인하기 위한
장치다. 지금 워치리스트 종목이 진입 신호까지 도달하도록 evaluate_entry의 임계값을
**env로만** 임시 완화한다. 아무 env도 없으면 오버라이드가 비어 evaluate_entry 기본 동작
그대로 — 평상시 영향 0. 전략 기본 임계값(indicators 상수)은 건드리지 않는다(ADR-009 방향).

완화 경로 두 가지 (개별 env가 프리셋보다 우선):
  1) ENTRY_PROFILE=verify — 진입까지 보장하는 프리셋 묶음(아래 PRESET_VERIFY).
  2) 개별 env — 필요한 항목만 완화(ENTRY_TREND_BYPASS 등).

이 모듈은 순수하다 — env(dict)만 읽고 네트워크·전역 상태를 모른다.
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Mapping

from worker.indicators import EntryResult, evaluate_entry

# env 키 → (evaluate_entry 키워드 인자, 파서 종류). 값이 비면(None/"") 무시 → 기본값 유지.
_INDIVIDUAL: dict[str, tuple[str, str]] = {
    "ENTRY_TREND_BYPASS": ("trend_bypass", "bool"),
    "ENTRY_REBOUND_REQUIRED": ("rebound_required", "int"),
    "ENTRY_PULLBACK_MIN_DROP": ("pullback_min_drop", "float"),
    "ENTRY_PULLBACK_MAX_DROP": ("pullback_max_drop", "float"),
    "ENTRY_RSI_THRESHOLD": ("rsi_threshold", "float"),
}

# ENTRY_PROFILE=verify 프리셋: 데이터만 충분하면 진입까지 도달하도록 최소 완화.
#   - trend_bypass: 추세 필터 우회(상승장 아니어도 통과)
#   - pullback 0~99%: 사실상 항상 눌림목 범위
#   - rebound_required=1: 반등 신호 1개만 있어도 통과
#   - rsi_threshold=100: RSI가 항상 과매도로 잡혀 반등 신호 1개 보장
PRESET_VERIFY: dict[str, Any] = {
    "trend_bypass": True,
    "pullback_min_drop": 0.0,
    "pullback_max_drop": 0.99,
    "rebound_required": 1,
    "rsi_threshold": 100.0,
}

Evaluator = Callable[..., EntryResult]


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in ("true", "1", "yes", "on")


def _parse(raw: str, kind: str) -> Any:
    if kind == "bool":
        return _parse_bool(raw)
    if kind == "int":
        return int(raw)
    return float(raw)


def load_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    """env에서 evaluate_entry 오버라이드를 읽는다. 아무 완화도 없으면 빈 dict(=기본값).

    ENTRY_PROFILE=verify 프리셋을 먼저 깔고, 개별 env가 있으면 그 위에 덮는다(개별 우선).
    """
    overrides: dict[str, Any] = {}
    if (env.get("ENTRY_PROFILE") or "").strip().lower() == "verify":
        overrides.update(PRESET_VERIFY)
    for env_key, (param, kind) in _INDIVIDUAL.items():
        raw = env.get(env_key)
        if raw is None or raw.strip() == "":
            continue  # 미설정 → 기본값(또는 프리셋) 유지
        overrides[param] = _parse(raw, kind)
    return overrides


def profile_active(env: Mapping[str, str]) -> bool:
    """완화가 하나라도 걸려 있으면 True(시작 로그 경고용)."""
    return bool(load_overrides(env))


def describe(env: Mapping[str, str]) -> str:
    """활성화된 완화 항목을 사람이 읽는 한 줄로(로그용)."""
    overrides = load_overrides(env)
    return ", ".join(f"{k}={v}" for k, v in sorted(overrides.items())) or "(없음)"


def build_evaluator(
    env: Mapping[str, str],
    base: Evaluator = evaluate_entry,
    base_overrides: dict[str, Any] | None = None,
) -> Evaluator:
    """evaluator를 만든다. base_overrides(예: DB 전략설정)를 깔고 env 완화를 그 위에 덮는다.

    우선순위: **env 완화(검증 의도) > base_overrides(DB 설정) > 전략 코드 기본값.**
    아무 오버라이드도 없으면 base(evaluate_entry) 그대로(평상시 영향 0).
    """
    overrides: dict[str, Any] = dict(base_overrides or {})
    overrides.update(load_overrides(env))  # env가 base 위에 우선
    if not overrides:
        return base
    return functools.partial(base, **overrides)
