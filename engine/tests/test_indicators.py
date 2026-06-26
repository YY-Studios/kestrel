"""이동평균(SMA)·추세 필터 테스트 (지표 슬라이스 1).

순수 함수라 mock 불필요 — 고정 입력 → 기대 출력. 외부 네트워크 0.
"""

from __future__ import annotations

import pytest

from worker.indicators import (
    BollingerResult,
    MacdResult,
    PullbackResult,
    RsiResult,
    TrendResult,
    bollinger_bands,
    decide_entry,
    ema,
    evaluate_bollinger,
    evaluate_entry,
    evaluate_macd,
    evaluate_pullback,
    evaluate_rsi,
    macd,
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


# --- EMA / MACD (시나리오1 3단계 신호 중 마지막: 히스토그램 반등) ----------

def test_ema_first_value_seed_known() -> None:
    # 첫값 seed, alpha=2/(period+1). period=3 → alpha=0.5
    # [1,2,3,4,5] → 1, 1.5, 2.25, 3.125, 4.0625
    assert ema([1, 2, 3, 4, 5], 3) == pytest.approx([1.0, 1.5, 2.25, 3.125, 4.0625])


def test_ema_period_one_is_identity() -> None:
    assert ema([5.0, 7.0, 9.0], 1) == pytest.approx([5.0, 7.0, 9.0])  # alpha=1


def test_ema_invalid_period_raises() -> None:
    with pytest.raises(ValueError):
        ema([1, 2, 3], 0)


def test_macd_wiring_matches_ema() -> None:
    # macd_line = EMA(fast)-EMA(slow), histogram = macd_line - signal_line
    closes = [5.0, 4.0, 3.0, 2.0, 3.0]
    m, s, h = macd(closes, fast=2, slow=3, signal=2)
    ef, es = ema(closes, 2)[-1], ema(closes, 3)[-1]
    assert m == pytest.approx(ef - es)
    assert h == pytest.approx(m - s)


def test_macd_insufficient_none() -> None:
    assert macd([1, 2, 3], fast=12, slow=26, signal=9) is None  # len < slow+signal


def test_evaluate_macd_histogram_rebound_true() -> None:
    # 하락하다 마지막에 반등 → 히스토그램이 음수 구간에서 증가 전환
    r = evaluate_macd([5.0, 4.0, 3.0, 2.0, 3.0], fast=2, slow=3, signal=2)
    assert r.evaluable is True
    assert r.rebound is True


def test_evaluate_macd_accelerating_decline_false() -> None:
    # 가속 하락 → 히스토그램 계속 감소 → 반등 아님
    r = evaluate_macd([10.0, 9.0, 7.0, 4.0, 0.0], fast=2, slow=3, signal=2)
    assert r.rebound is False


def test_evaluate_macd_positive_not_rebound() -> None:
    # 상승 추세(히스토그램 양수)는 "음수 구간 반등"이 아니다 — 단순 양수로 True 주지 않음
    r = evaluate_macd([1.0, 2.0, 3.0, 4.0, 5.0], fast=2, slow=3, signal=2)
    assert r.rebound is False


def test_evaluate_macd_insufficient_not_evaluable() -> None:
    r = evaluate_macd([1.0, 2.0, 3.0], fast=12, slow=26, signal=9)
    assert r.evaluable is False
    assert r.rebound is False


# --- 눌림목 (시나리오1 2단계, 최근 고점 대비 -5~-10%) ----------------------

def test_pullback_in_range_true() -> None:
    # 최근 고점 100, 현재 92 → 8% 하락 → 범위(5~10%) 내 → True
    r = evaluate_pullback([100.0, 95.0, 92.0], lookback=3)
    assert r.evaluable is True
    assert r.recent_high == 100.0
    assert r.drop_pct == pytest.approx(0.08)
    assert r.in_pullback is True


def test_pullback_boundary_min_inclusive() -> None:
    # 정확히 5% → 포함(이상)
    r = evaluate_pullback([100.0, 98.0, 95.0], lookback=3)
    assert r.drop_pct == pytest.approx(0.05)
    assert r.in_pullback is True


def test_pullback_boundary_max_inclusive() -> None:
    # 정확히 10% → 포함(이하)
    r = evaluate_pullback([100.0, 95.0, 90.0], lookback=3)
    assert r.drop_pct == pytest.approx(0.10)
    assert r.in_pullback is True


def test_pullback_too_shallow_false() -> None:
    r = evaluate_pullback([100.0, 98.0, 97.0], lookback=3)  # 3% 하락
    assert r.in_pullback is False


def test_pullback_too_deep_false() -> None:
    r = evaluate_pullback([100.0, 90.0, 85.0], lookback=3)  # 15% 하락
    assert r.in_pullback is False


def test_pullback_at_new_high_false() -> None:
    r = evaluate_pullback([90.0, 95.0, 100.0], lookback=3)  # 현재가가 고점 → 0%
    assert r.drop_pct == pytest.approx(0.0)
    assert r.in_pullback is False


def test_pullback_current_price_override() -> None:
    # 고점은 종가에서, 현재가는 인자로(실시간가 가정)
    r = evaluate_pullback([100.0, 99.0, 98.0], current_price=92.0, lookback=3)
    assert r.recent_high == 100.0
    assert r.in_pullback is True  # 8% 하락


def test_pullback_insufficient_not_evaluable() -> None:
    r = evaluate_pullback([100.0, 95.0], lookback=3)  # lookback 미만
    assert r.evaluable is False
    assert r.in_pullback is False


# --- 진입 판단 종합 (시나리오1 두뇌) ---------------------------------------
# 결합 로직은 decide_entry로 합성 *Result를 주입해 정밀 검증한다.

def _trend(passed: bool, evaluable: bool = True) -> TrendResult:
    return TrendResult(sma_short=21.0, sma_long=20.0, current_price=22.0, evaluable=evaluable, passed=passed)


def _pb(in_pullback: bool, evaluable: bool = True) -> PullbackResult:
    return PullbackResult(recent_high=100.0, current_price=92.0, drop_pct=0.08, evaluable=evaluable, in_pullback=in_pullback)


def _rsi(oversold: bool, evaluable: bool = True) -> RsiResult:
    return RsiResult(value=30.0, evaluable=evaluable, oversold=oversold)


def _bb(signal: bool, evaluable: bool = True) -> BollingerResult:
    return BollingerResult(middle=10.0, upper=12.0, lower=8.0, value=8.5, evaluable=evaluable, signal=signal)


def _macd(rebound: bool, evaluable: bool = True) -> MacdResult:
    return MacdResult(macd_line=-0.1, signal_line=-0.2, histogram=0.1, evaluable=evaluable, rebound=rebound)


def test_decide_entry_all_pass_two_of_three() -> None:
    r = decide_entry(_trend(True), _pb(True), _rsi(True), _bb(True), _macd(False))
    assert r.rebound_count == 2
    assert r.evaluable is True
    assert r.enter is True


def test_decide_entry_three_of_three() -> None:
    r = decide_entry(_trend(True), _pb(True), _rsi(True), _bb(True), _macd(True))
    assert r.rebound_count == 3
    assert r.enter is True


def test_decide_entry_one_of_three_fails() -> None:
    r = decide_entry(_trend(True), _pb(True), _rsi(True), _bb(False), _macd(False))
    assert r.rebound_count == 1
    assert r.enter is False


def test_decide_entry_trend_gate() -> None:
    # 추세 미통과면 눌림목·반등이 충족돼도 진입 불가(게이팅)
    r = decide_entry(_trend(False), _pb(True), _rsi(True), _bb(True), _macd(True))
    assert r.enter is False


def test_decide_entry_pullback_required() -> None:
    r = decide_entry(_trend(True), _pb(False), _rsi(True), _bb(True), _macd(True))
    assert r.enter is False


def test_decide_entry_not_evaluable_blocks() -> None:
    # 한 단계라도 판단불가면 전체 진입 불가 + evaluable=False (불완전 근거로 매수 안 함)
    r = decide_entry(_trend(True), _pb(True), _rsi(True, evaluable=False), _bb(True), _macd(True))
    assert r.evaluable is False
    assert r.enter is False


def test_decide_entry_custom_required() -> None:
    # 필요 개수를 1로 낮추면 1/3도 진입
    r = decide_entry(_trend(True), _pb(True), _rsi(True), _bb(False), _macd(False), rebound_required=1)
    assert r.enter is True


def test_decide_entry_result_carries_evidence() -> None:
    trend, pb, rsi_r, bb, macd_r = _trend(True), _pb(True), _rsi(True), _bb(True), _macd(False)
    r = decide_entry(trend, pb, rsi_r, bb, macd_r)
    assert r.trend is trend and r.pullback is pb
    assert r.rsi is rsi_r and r.bollinger is bb and r.macd is macd_r
    assert r.rebound_required == 2


def test_evaluate_entry_wires_subresults_no_pullback() -> None:
    # 신고가 상승추세(눌림목 없음) → enter False, 단 추세는 통과(근거로 남음)
    closes = [float(x) for x in range(1, 71)]  # 1..70 상승, 현재=70(신고가)
    r = evaluate_entry(closes)
    assert r.trend.passed is True
    assert r.pullback.in_pullback is False
    assert r.enter is False


def test_evaluate_entry_insufficient_not_evaluable() -> None:
    r = evaluate_entry([1.0, 2.0, 3.0])
    assert r.evaluable is False
    assert r.enter is False
