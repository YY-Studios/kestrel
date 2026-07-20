"""전략설정(DB) 검증·매핑 — 순수 로직, 네트워크 없음.

전략설정 화면이 strategy_settings 테이블에 저장한 값을 engine이 읽어 실제 판단에 쓴다.
engine은 api를 import하지 않으므로(패키지 경계) 안전 범위·기본값을 여기에 자체 보유한다
(api/app/strategy_settings.py SPECS와 동일 범위 — 어긋나면 안 됨).

안전 원칙(engine 로직을 건드리므로):
  - 폴백: row 없음/누락/형변환 실패 → 그 필드는 전략 코드 기본값.
  - 범위 재검증: DB에 직접 넣은 이상값이 매매에 새지 않게 범위 밖이면 기본값 + 경고.
  - 교차 검증: 눌림목 min > max면 둘 다 기본값.
api의 검증만 믿지 않는다(누가 SQL로 직접 넣을 수 있으므로).
"""

from __future__ import annotations

import logging
from typing import Any

from worker import indicators
from worker.orders import ORDER_MAX_POSITIONS

logger = logging.getLogger("kestrel.engine")

# 전략 코드 기본값과 일치(테스트로 고정). %는 분수(0.08=8%).
DEFAULTS: dict[str, Any] = {
    "rsi_threshold": indicators.RSI_OVERSOLD,      # 35.0
    "pullback_min": indicators.PULLBACK_MIN_DROP,  # 0.05
    "pullback_max": indicators.PULLBACK_MAX_DROP,  # 0.10
    "rebound_required": indicators.REBOUND_REQUIRED,  # 2
    "take_profit_pct": 0.08,   # OrderExecutor target_pct 기본
    "stop_loss_pct": 0.05,     # OrderExecutor stop_pct 기본
    "total_capital": 10000.0,
    "max_positions": ORDER_MAX_POSITIONS,  # 3
}

# 안전 범위 (api SPECS와 동일). key: (min, max, is_int)
RANGES: dict[str, tuple[float, float, bool]] = {
    "rsi_threshold": (25, 45, False),
    "pullback_min": (0.02, 0.10, False),
    "pullback_max": (0.05, 0.20, False),
    "rebound_required": (1, 3, True),
    "take_profit_pct": (0.03, 0.15, False),
    "stop_loss_pct": (0.01, 0.10, False),
    "total_capital": (100, 1_000_000, False),
    "max_positions": (1, 5, True),
}


def validate_strategy_settings(row: dict | None) -> dict:
    """DB row → 검증된 전체 설정(8개 키). 누락/범위밖/형변환 실패 필드는 기본값 + 경고.

    row=None/빈 dict면 전부 기본값(폴백). 각 필드는 독립적으로 검증 — 한 필드가 이상해도
    나머지는 유효값을 쓴다. 마지막에 눌림목 min ≤ max 교차 검증.
    """
    result = dict(DEFAULTS)
    if not row:
        return result

    for key, (lo, hi, is_int) in RANGES.items():
        if key not in row or row[key] is None:
            continue  # 누락/null → 기본값 유지(조용히)
        raw = row[key]
        if isinstance(raw, bool):  # bool이 int(1/0)로 새지 않게
            logger.warning("전략설정 %s 형식 오류(bool %r) — 기본값 %s 사용", key, raw, DEFAULTS[key])
            continue
        try:
            val: Any = int(raw) if is_int else float(raw)
        except (TypeError, ValueError):
            logger.warning("전략설정 %s 형변환 실패(%r) — 기본값 %s 사용", key, raw, DEFAULTS[key])
            continue
        if val < lo or val > hi:
            logger.warning(
                "전략설정 %s 범위 밖(%s ∉ [%s, %s]) — 기본값 %s 사용", key, val, lo, hi, DEFAULTS[key]
            )
            continue
        result[key] = val

    if result["pullback_min"] > result["pullback_max"]:
        logger.warning(
            "전략설정 눌림목 min(%s) > max(%s) — 둘 다 기본값으로 대체",
            result["pullback_min"], result["pullback_max"],
        )
        result["pullback_min"] = DEFAULTS["pullback_min"]
        result["pullback_max"] = DEFAULTS["pullback_max"]

    return result


def evaluate_overrides(strat: dict) -> dict:
    """검증된 설정을 evaluate_entry 키워드 인자로 매핑(진입 임계값 주입용)."""
    return {
        "rsi_threshold": strat["rsi_threshold"],
        "pullback_min_drop": strat["pullback_min"],
        "pullback_max_drop": strat["pullback_max"],
        "rebound_required": strat["rebound_required"],
    }
