"""이동평균(SMA)·추세 필터 테스트 (지표 슬라이스 1).

순수 함수라 mock 불필요 — 고정 입력 → 기대 출력. 외부 네트워크 0.
"""

from __future__ import annotations

import pytest

from worker.indicators import (
    bollinger_bands,
    evaluate_bollinger,
    evaluate_rsi,
    rsi,
    sma,
    trend_filter,
)


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


# --- RSI (Wilder smoothing, 시나리오1 3단계 반등 신호 중 하나) --------------

def test_rsi_wilder_known_value() -> None:
    # period=2 손계산: closes [10,11,10,11,12]
    #   gains [1,0,1,1], losses [0,1,0,0]
    #   초기평균(2개): avg_gain=0.5, avg_loss=0.5
    #   smoothing: → (0.75,0.25) → (0.875,0.125), RS=7 → RSI=87.5
    assert rsi([10, 11, 10, 11, 12], period=2) == pytest.approx(87.5)


def test_rsi_all_gains_near_100() -> None:
    closes = [float(x) for x in range(1, 30)]  # 계속 상승만
    assert rsi(closes, period=14) == pytest.approx(100.0)


def test_rsi_all_losses_near_0() -> None:
    closes = [float(x) for x in range(30, 0, -1)]  # 계속 하락만
    assert rsi(closes, period=14) == pytest.approx(0.0)


def test_rsi_insufficient_data_none() -> None:
    assert rsi([1, 2, 3], period=14) is None  # period+1 미만
    assert rsi(list(range(15)), period=14) is not None  # 정확히 period+1이면 계산됨


def test_rsi_invalid_period_raises() -> None:
    with pytest.raises(ValueError):
        rsi([1, 2, 3], period=0)


def test_evaluate_rsi_oversold_true() -> None:
    closes = [float(x) for x in range(30, 0, -1)]  # 하락 → RSI 0
    r = evaluate_rsi(closes, period=14, threshold=35.0)
    assert r.evaluable is True
    assert r.oversold is True


def test_evaluate_rsi_not_oversold() -> None:
    closes = [float(x) for x in range(1, 30)]  # 상승 → RSI 100
    r = evaluate_rsi(closes, period=14, threshold=35.0)
    assert r.oversold is False


def test_evaluate_rsi_threshold_is_inclusive() -> None:
    # 경계: RSI == threshold 이면 과매도(<=)로 본다.
    closes = [10, 11, 10, 11, 12]
    v = rsi(closes, period=2)  # 87.5
    assert evaluate_rsi(closes, period=2, threshold=v).oversold is True  # 87.5 <= 87.5
    assert evaluate_rsi(closes, period=2, threshold=v - 0.01).oversold is False


def test_evaluate_rsi_insufficient_not_evaluable() -> None:
    r = evaluate_rsi([1, 2, 3], period=14)
    assert r.evaluable is False
    assert r.oversold is False  # 데이터 부족을 과매도로 오판하지 않는다


# --- 볼린저밴드 (모집단 std, 시나리오1 3단계 신호 중 하나) ------------------

def test_bollinger_bands_known_value() -> None:
    # 손계산: [2,4,4,4,5,5,7,9], period=8 → mean=5, 모집단 std=2
    #   → middle=5, upper=5+2*2=9, lower=5-2*2=1
    mid, up, lo = bollinger_bands([2, 4, 4, 4, 5, 5, 7, 9], period=8, num_std=2.0)
    assert (mid, up, lo) == pytest.approx((5.0, 9.0, 1.0))


def test_bollinger_insufficient_none() -> None:
    assert bollinger_bands([1, 2, 3], period=20) is None


def test_bollinger_invalid_period_raises() -> None:
    with pytest.raises(ValueError):
        bollinger_bands([1, 2, 3], period=0)


def test_evaluate_bollinger_touch_then_recover_true() -> None:
    # 직전 봉이 하단 터치(<=lower) → 최신 봉이 하단 위로 + 위로 반등(틱업)
    closes = [20.0, 20.0, 20.0, 20.0, 8.0, 21.0]
    r = evaluate_bollinger(closes, period=5, num_std=2.0)
    assert r.evaluable is True
    assert r.signal is True


def test_evaluate_bollinger_still_falling_false() -> None:
    # 하단 터치 후 계속 하락(틱다운) → 복귀 아님 → False
    closes = [20.0, 20.0, 20.0, 20.0, 8.0, 7.0]
    r = evaluate_bollinger(closes, period=5, num_std=2.0)
    assert r.signal is False


def test_evaluate_bollinger_within_band_false() -> None:
    # 밴드 안에서만 진동 → 하단 터치 자체가 없음 → False
    closes = [20.0, 21.0, 20.0, 21.0, 20.0, 21.0]
    r = evaluate_bollinger(closes, period=5, num_std=2.0)
    assert r.signal is False


def test_evaluate_bollinger_insufficient_not_evaluable() -> None:
    r = evaluate_bollinger([1.0, 2.0, 3.0], period=20)
    assert r.evaluable is False
    assert r.signal is False  # 데이터 부족을 신호로 오판하지 않는다
