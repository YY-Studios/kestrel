"""이동평균(SMA)·추세 필터 테스트 (지표 슬라이스 1).

순수 함수라 mock 불필요 — 고정 입력 → 기대 출력. 외부 네트워크 0.
"""

from __future__ import annotations

import pytest

from worker.indicators import sma, trend_filter


# --- SMA ------------------------------------------------------------------

def test_sma_basic() -> None:
    closes = list(range(1, 21))  # 1..20
    assert sma(closes, 20) == 10.5  # (1+..+20)/20
    assert sma(closes, 5) == 18.0  # (16+17+18+19+20)/5


def test_sma_uses_last_n_only() -> None:
    closes = [10, 20, 30, 40, 50]
    assert sma(closes, 2) == 45.0  # (40+50)/2


def test_sma_insufficient_data_returns_none() -> None:
    assert sma([1, 2, 3], 5) is None


def test_sma_invalid_period_raises() -> None:
    with pytest.raises(ValueError):
        sma([1, 2, 3], 0)


# --- 추세 필터 (시나리오1 1단계: SMA20 > SMA60 AND 현재가 > SMA60) ---------

def test_trend_filter_uptrend_passes() -> None:
    closes = [float(x) for x in range(1, 71)]  # 1..70 상승
    r = trend_filter(closes)  # 현재가 미지정 → 마지막 종가(70) 사용
    assert r.evaluable is True
    assert r.sma_short > r.sma_long  # 최근 20일 평균 > 60일 평균
    assert r.current_price > r.sma_long
    assert r.passed is True


def test_trend_filter_downtrend_fails() -> None:
    closes = [float(x) for x in range(70, 0, -1)]  # 70..1 하락
    r = trend_filter(closes)
    assert r.evaluable is True
    assert r.passed is False  # SMA20 < SMA60


def test_trend_filter_insufficient_data_not_evaluable() -> None:
    r = trend_filter([float(x) for x in range(1, 11)])  # 10일치뿐(60 미만)
    assert r.evaluable is False
    assert r.passed is False  # 데이터 부족을 "통과"로 오판하지 않는다


def test_trend_filter_flat_not_passed() -> None:
    # 완전 평탄 → SMA20 == SMA60, 현재가 == SMA60 → 부등호 불성립 → 미통과
    closes = [100.0] * 70
    r = trend_filter(closes)
    assert r.evaluable is True
    assert r.passed is False


def test_trend_filter_current_price_override_below_long_fails() -> None:
    # 상승 추세라 SMA20>SMA60지만, 현재가를 SMA60 아래로 주면 미통과.
    closes = [float(x) for x in range(1, 71)]
    r = trend_filter(closes, current_price=5.0)
    assert r.sma_short > r.sma_long
    assert r.passed is False  # 현재가 5 < SMA60
