"""전략설정 조회/저장 — Supabase strategy_settings(단일 행 id=1).

시나리오1의 임계값(RSI·눌림목·반등 개수·익절·손절·투자금액·최대종목수)을 화면에서
조절해 DB에 저장한다. **안전 범위(min/max)를 서버에서도 검증**한다(프론트 슬라이더만 믿지 않음).

주의(이번 슬라이스 경계): 저장만 한다. **engine이 이 값을 읽어 매매에 쓰는 연결은 다음 단계.**
따라서 저장돼도 실제 판단/주문에는 아직 영향이 없다(화면 안내로 오해 방지).

두 계층: 순수 검증(coerce_and_validate·merged_settings·validate_full) + 얇은 조회/저장 + 라우터.
저장 단위는 코드가 쓰는 값과 맞춘다 — %는 분수(0.08=8%), RSI·개수는 정수/실수 그대로.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.supabase_client import get_supabase

logger = logging.getLogger("kestrel.api")

TABLE = "strategy_settings"

# 조절 파라미터 스펙(단일 진실). min/max=안전 범위. type=저장 타입. format/unit=화면 표시.
# 기본값(default)은 현재 전략 기본값(indicators/orders/execution)과 일치.
SPECS: list[dict] = [
    {"key": "rsi_threshold", "label": "RSI 과매도 기준", "group": "entry",
     "min": 25, "max": 45, "step": 1, "type": "float", "default": 35,
     "format": "num", "unit": "", "min_label": "25 (엄격)", "max_label": "45 (느슨)"},
    {"key": "pullback_min", "label": "눌림목 최소 하락", "group": "entry",
     "min": 0.02, "max": 0.10, "step": 0.01, "type": "float", "default": 0.05,
     "format": "pct", "unit": "%", "min_label": "2%", "max_label": "10%"},
    {"key": "pullback_max", "label": "눌림목 최대 하락", "group": "entry",
     "min": 0.05, "max": 0.20, "step": 0.01, "type": "float", "default": 0.10,
     "format": "pct", "unit": "%", "min_label": "5%", "max_label": "20%"},
    {"key": "rebound_required", "label": "반등 신호 필요 개수", "group": "entry",
     "min": 1, "max": 3, "step": 1, "type": "int", "default": 2,
     "format": "count", "unit": "개", "min_label": "1개", "max_label": "3개"},
    {"key": "take_profit_pct", "label": "익절 목표", "group": "exit",
     "min": 0.03, "max": 0.15, "step": 0.01, "type": "float", "default": 0.08,
     "format": "pct_plus", "unit": "%", "min_label": "+3%", "max_label": "+15%"},
    {"key": "stop_loss_pct", "label": "손절선", "group": "exit",
     "min": 0.01, "max": 0.10, "step": 0.01, "type": "float", "default": 0.05,
     "format": "pct_minus", "unit": "%", "min_label": "−1% (타이트)", "max_label": "−10% (넉넉)"},
    {"key": "total_capital", "label": "투자 금액", "group": "capital",
     "min": 100, "max": 1_000_000, "step": 100, "type": "float", "default": 10000,
     "format": "usd", "unit": "$", "min_label": "$100", "max_label": "$1,000,000"},
    {"key": "max_positions", "label": "최대 보유 종목", "group": "capital",
     "min": 1, "max": 5, "step": 1, "type": "int", "default": 3,
     "format": "count", "unit": "종목", "min_label": "1종목", "max_label": "5종목"},
]

_SPEC_BY_KEY = {s["key"]: s for s in SPECS}
DEFAULTS: dict[str, Any] = {s["key"]: s["default"] for s in SPECS}

router = APIRouter()


def coerce_and_validate(values: dict) -> dict:
    """제공된 키만 타입 변환 + 안전 범위 검증. 알 수 없는 키/타입 오류/범위 밖이면 ValueError."""
    cleaned: dict[str, Any] = {}
    for key, raw in values.items():
        spec = _SPEC_BY_KEY.get(key)
        if spec is None:
            raise ValueError(f"알 수 없는 설정: {key}")
        if isinstance(raw, bool):  # bool이 int(1/0)로 새지 않게 먼저 막는다
            raise ValueError(f"{spec['label']}: 숫자가 아닙니다")
        try:
            num: Any = int(raw) if spec["type"] == "int" else float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{spec['label']}: 숫자가 아닙니다")
        if num < spec["min"] or num > spec["max"]:
            raise ValueError(
                f"{spec['label']}: 허용 범위({spec['min']}~{spec['max']})를 벗어남 (받음 {num})"
            )
        cleaned[key] = num
    return cleaned


def merged_settings(current: dict, patch: dict) -> dict:
    """기본값 위에 현재값·patch를 덮어 전체 설정을 만든다(DEFAULTS 키만 — 여분 컬럼 제거)."""
    combined = {**DEFAULTS, **(current or {}), **(patch or {})}
    return {k: combined[k] for k in DEFAULTS}


def validate_full(settings: dict) -> dict:
    """전체 설정 교차 검증: 눌림목 최소 ≤ 최대. 위반 시 ValueError."""
    if settings["pullback_min"] > settings["pullback_max"]:
        raise ValueError("눌림목 최소 하락이 최대 하락보다 클 수 없습니다")
    return settings


def _fetch_settings(client: Any) -> dict | None:
    resp = client.table(TABLE).select("*").eq("id", 1).limit(1).execute()
    rows = list(getattr(resp, "data", None) or [])
    return rows[0] if rows else None


def _save_settings(client: Any, settings: dict) -> None:
    client.table(TABLE).upsert({"id": 1, **settings}).execute()


@router.get("/api/strategy-settings")
def get_strategy_settings() -> dict:
    """현재 전략설정 + 스펙(슬라이더 범위). 저장된 값이 없거나 아직 테이블이 없으면 기본값.

    조회 실패(테이블 미생성 등)여도 기본값으로 폴백해 화면이 뜨게 한다(과제: "없으면 기본값").
    persisted=False면 DB에서 읽지 못하고 기본값을 보여주는 상태(저장은 POST에서 별도 검증).
    """
    persisted = True
    row: dict | None = None
    try:
        row = _fetch_settings(get_supabase())
    except Exception as exc:
        logger.warning("전략설정 조회 실패(기본값 폴백): %s", type(exc).__name__)
        persisted = False
    return {"settings": merged_settings(row or {}, {}), "spec": SPECS, "persisted": persisted}


@router.post("/api/strategy-settings")
def save_strategy_settings(payload: dict = Body(...)) -> dict:
    """전략설정 저장. 서버에서 안전 범위 검증 — 범위 밖/알 수 없는 키면 400.

    engine 반영은 다음 단계 — 저장만 한다(실매매엔 아직 영향 없음).
    """
    values = payload.get("settings") if isinstance(payload.get("settings"), dict) else payload
    try:
        cleaned = coerce_and_validate(values or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        current = _fetch_settings(get_supabase()) or {}
    except Exception as exc:
        logger.warning("전략설정 조회(저장 전) 실패: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="전략설정을 저장하지 못했습니다") from exc

    final = merged_settings(current, cleaned)
    try:
        validate_full(final)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        _save_settings(get_supabase(), final)
    except Exception as exc:
        logger.warning("전략설정 저장 실패: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="전략설정을 저장하지 못했습니다") from exc

    return {"settings": final, "spec": SPECS}
