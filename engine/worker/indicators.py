"""기술 지표 계산 (순수 함수, 외부 의존 없음).

입력은 broker-client에서 받은 종가 리스트(과거→최신). KIS 연동(broker-client)과
계산 로직을 분리한다 — 이 모듈은 네트워크를 모른다.

이번 슬라이스: 단순이동평균(SMA) + 시나리오1 1단계 추세 필터.
RSI·볼린저·MACD·눌림목·신호 종합은 다음 슬라이스들.
"""

from __future__ import annotations

from dataclasses import dataclass

# 시나리오1 1단계 기본 기간 (임계값은 추후 config로 — ADR-009).
TREND_SHORT = 20
TREND_LONG = 60


def sma(closes: list[float], period: int) -> float | None:
    """단순이동평균: 마지막 `period`개 종가의 평균. 데이터가 부족하면 None.

    closes는 과거→최신 순. period<=0이면 ValueError.
    """
    if period <= 0:
        raise ValueError(f"period는 1 이상이어야 한다 (받음: {period})")
    if len(closes) < period:
        return None
    window = closes[-period:]
    return sum(window) / period


@dataclass(frozen=True)
class TrendResult:
    """추세 필터 결과. 근거(sma)도 함께 담아 로그/UI/분석에 쓰게 한다."""

    sma_short: float | None
    sma_long: float | None
    current_price: float | None
    evaluable: bool  # 데이터가 충분해 판단 가능한가
    passed: bool  # 추세 필터 통과 여부


def trend_filter(
    closes: list[float],
    current_price: float | None = None,
    *,
    short: int = TREND_SHORT,
    long: int = TREND_LONG,
) -> TrendResult:
    """시나리오1 1단계 추세 필터: SMA(short) > SMA(long) AND 현재가 > SMA(long).

    current_price 미지정 시 마지막 종가를 사용한다.
    데이터가 부족(둘 중 하나라도 SMA를 못 구함)하면 evaluable=False, passed=False
    — 데이터 부족을 "통과"로 오판하지 않는다.
    """
    cp = current_price if current_price is not None else (closes[-1] if closes else None)
    s = sma(closes, short)
    longer = sma(closes, long)

    evaluable = s is not None and longer is not None and cp is not None
    passed = bool(evaluable and s > longer and cp > longer)
    return TrendResult(
        sma_short=s, sma_long=longer, current_price=cp, evaluable=evaluable, passed=passed
    )
