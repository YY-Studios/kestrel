"""기술 지표 계산 (순수 함수, 외부 의존 없음).

입력은 broker-client에서 받은 종가 리스트(과거→최신). KIS 연동(broker-client)과
계산 로직을 분리한다 — 이 모듈은 네트워크를 모른다.

이번 슬라이스: 단순이동평균(SMA) + 시나리오1 1단계 추세 필터.
RSI·볼린저·MACD·눌림목·신호 종합은 다음 슬라이스들.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

# 시나리오1 1단계 기본 기간 (임계값은 추후 config로 — ADR-009).
TREND_SHORT = 20
TREND_LONG = 60

# 시나리오1 3단계 반등 신호 중 하나: RSI 과매도.
RSI_PERIOD = 14
RSI_OVERSOLD = 35.0

# 시나리오1 3단계 반등 신호 중 하나: 볼린저 하단 터치 후 복귀.
BOLLINGER_PERIOD = 20
BOLLINGER_NUM_STD = 2.0

# 시나리오1 3단계 반등 신호 중 하나: MACD 히스토그램 반등.
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# 시나리오1 2단계: 눌림목 — 최근 고점 대비 -5~-10% 하락.
PULLBACK_LOOKBACK = 20
PULLBACK_MIN_DROP = 0.05
PULLBACK_MAX_DROP = 0.10


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


def rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    """RSI (Wilder smoothing). 마지막 시점의 RSI(0~100). 데이터 부족 시 None.

    방식(일관 — 단순/지수 혼용 금지):
      1) 연속 종가 차이로 상승분(gain)·하락분(loss) 분리.
      2) 첫 평균 = 최초 `period`개 gain/loss의 단순평균.
      3) 이후 와일더 평활: avg = (이전평균 * (period-1) + 현재값) / period.
      4) RS = avg_gain / avg_loss, RSI = 100 - 100/(1 + RS).
    경계: avg_loss=0이면 상승만 → 100.0 (변동 없으면 50.0 중립).
    데이터는 최소 period+1개 종가가 필요(차이 period개).
    """
    if period <= 0:
        raise ValueError(f"period는 1 이상이어야 한다 (받음: {period})")
    if len(closes) < period + 1:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0  # 하락 없음(상승만) → 100, 완전 평탄 → 중립 50
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


@dataclass(frozen=True)
class RsiResult:
    """RSI 평가 결과. 근거(value)를 담아 로그/UI/분석에 쓰게 한다."""

    value: float | None
    evaluable: bool
    oversold: bool


def evaluate_rsi(
    closes: list[float], period: int = RSI_PERIOD, threshold: float = RSI_OVERSOLD
) -> RsiResult:
    """RSI를 계산해 과매도(<= threshold) 여부를 판정. 데이터 부족이면 판단 불가(과매도 아님)."""
    value = rsi(closes, period)
    evaluable = value is not None
    oversold = bool(evaluable and value <= threshold)
    return RsiResult(value=value, evaluable=evaluable, oversold=oversold)


def bollinger_bands(
    closes: list[float], period: int = BOLLINGER_PERIOD, num_std: float = BOLLINGER_NUM_STD
) -> tuple[float, float, float] | None:
    """볼린저밴드 (중간선=SMA, 상/하단=중간선 ± num_std×표준편차).

    표준편차는 **모집단(population, ddof=0)** 기준(`statistics.pstdev`) — 일관 사용.
    마지막 `period`개 종가로 계산. 데이터 부족 시 None. period<=0이면 ValueError.
    반환: (middle, upper, lower).
    """
    if period <= 0:
        raise ValueError(f"period는 1 이상이어야 한다 (받음: {period})")
    if len(closes) < period:
        return None
    window = closes[-period:]
    middle = sum(window) / period
    sd = statistics.pstdev(window)  # 모집단 표준편차(ddof=0)
    return middle, middle + num_std * sd, middle - num_std * sd


@dataclass(frozen=True)
class BollingerResult:
    """볼린저 평가 결과. 현재 밴드와 근거를 담는다. signal = 하단 터치 후 복귀."""

    middle: float | None
    upper: float | None
    lower: float | None
    value: float | None  # 현재(최신) 종가
    evaluable: bool
    signal: bool


def evaluate_bollinger(
    closes: list[float], period: int = BOLLINGER_PERIOD, num_std: float = BOLLINGER_NUM_STD
) -> BollingerResult:
    """"하단 터치 후 복귀" 판정 — 단순히 "지금 하단 아래"만으로 신호를 주지 않는다.

    정의(셋 다 충족 시 signal=True):
      1) 직전 봉이 그 시점 밴드의 하단 이하로 내려갔다(터치, `<=` 포함).
      2) 최신 봉이 현재 밴드의 하단 위로 올라왔다(`>` 하단).
      3) 최신 종가가 직전 종가보다 높다(실제로 위로 반등 = 복귀, 계속 하락이 아님).
    각 봉은 자신의 시점 밴드로 비교한다. 데이터는 period+1개 필요(직전·현재 밴드).
    부족하면 evaluable=False, signal=False(오판 방지).
    """
    current = bollinger_bands(closes, period, num_std)
    value = closes[-1] if closes else None

    if current is None or len(closes) < period + 1:
        mid, up, lo = current if current is not None else (None, None, None)
        return BollingerResult(mid, up, lo, value, evaluable=False, signal=False)

    prev = bollinger_bands(closes[:-1], period, num_std)
    mid, up, lo = current
    _, _, lo_prev = prev  # type: ignore[misc]

    touched = closes[-2] <= lo_prev
    back_above = closes[-1] > lo
    ticked_up = closes[-1] > closes[-2]
    signal = bool(touched and back_above and ticked_up)
    return BollingerResult(mid, up, lo, value, evaluable=True, signal=signal)


def ema(values: list[float], period: int) -> list[float]:
    """지수이동평균(EMA) 시리즈. **첫값 seed** 방식(pandas ewm adjust=False와 동일).

    ema[0] = values[0], 이후 ema[i] = α·values[i] + (1-α)·ema[i-1], α = 2/(period+1).
    입력과 같은 길이의 시리즈를 반환(빈 입력 → []). period<=0이면 ValueError.
    """
    if period <= 0:
        raise ValueError(f"period는 1 이상이어야 한다 (받음: {period})")
    if not values:
        return []
    alpha = 2.0 / (period + 1)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def _macd_series(
    closes: list[float], fast: int, slow: int, signal: int
) -> tuple[list[float], list[float], list[float]]:
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = ema(macd_line, signal)
    histogram = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, histogram


def macd(
    closes: list[float],
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> tuple[float, float, float] | None:
    """MACD 최신값 (macd_line, signal_line, histogram). 데이터 부족 시 None.

    macd_line = EMA(fast) - EMA(slow), signal_line = EMA(macd_line, signal),
    histogram = macd_line - signal_line. EMA는 첫값 seed(위 ema 참고).
    워밍업을 위해 최소 slow+signal개 종가가 필요(미만이면 None).
    """
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("fast/slow/signal은 모두 1 이상이어야 한다")
    if len(closes) < slow + signal:
        return None
    macd_line, signal_line, histogram = _macd_series(closes, fast, slow, signal)
    return macd_line[-1], signal_line[-1], histogram[-1]


@dataclass(frozen=True)
class MacdResult:
    """MACD 평가 결과. rebound = 히스토그램이 음수 구간에서 증가 전환(반등 조짐)."""

    macd_line: float | None
    signal_line: float | None
    histogram: float | None
    evaluable: bool
    rebound: bool


def evaluate_macd(
    closes: list[float],
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> MacdResult:
    """히스토그램 "반등" 판정 — 단순 "히스토그램>0"이 아니다.

    정의(둘 다 충족 시 rebound=True):
      1) 직전 히스토그램이 음수다(눌림/하락 모멘텀 구간).
      2) 최신 히스토그램이 직전보다 크다(감소하다 증가로 전환 = 모멘텀 반등 조짐).
    데이터 부족(slow+signal 미만)이면 evaluable=False, rebound=False(오판 방지).
    """
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("fast/slow/signal은 모두 1 이상이어야 한다")
    if len(closes) < slow + signal:
        return MacdResult(None, None, None, evaluable=False, rebound=False)
    macd_line, signal_line, histogram = _macd_series(closes, fast, slow, signal)
    rebound = histogram[-2] < 0 and histogram[-1] > histogram[-2]
    return MacdResult(
        macd_line=macd_line[-1],
        signal_line=signal_line[-1],
        histogram=histogram[-1],
        evaluable=True,
        rebound=bool(rebound),
    )


@dataclass(frozen=True)
class PullbackResult:
    """눌림목 평가 결과. drop_pct = 최근 고점 대비 현재가 하락률(0.08 = 8% 하락)."""

    recent_high: float | None
    current_price: float | None
    drop_pct: float | None
    evaluable: bool
    in_pullback: bool


def evaluate_pullback(
    closes: list[float],
    current_price: float | None = None,
    lookback: int = PULLBACK_LOOKBACK,
    min_drop: float = PULLBACK_MIN_DROP,
    max_drop: float = PULLBACK_MAX_DROP,
) -> PullbackResult:
    """시나리오1 2단계 눌림목: 최근 고점 대비 현재가가 적당히 빠진 상태.

    recent_high = 최근 `lookback`개 **종가**의 최고값.
    drop_pct = (recent_high - current_price) / recent_high.
    **min_drop ≤ drop_pct ≤ max_drop**(양끝 포함: 5% 이상 10% 이하)이면 in_pullback=True.
    current_price 미지정 시 마지막 종가 사용. 데이터 부족(lookback 미만)·고점<=0이면 판단 불가.
    """
    if lookback <= 0:
        raise ValueError(f"lookback은 1 이상이어야 한다 (받음: {lookback})")
    cp = current_price if current_price is not None else (closes[-1] if closes else None)
    if len(closes) < lookback or cp is None:
        return PullbackResult(None, cp, None, evaluable=False, in_pullback=False)
    recent_high = max(closes[-lookback:])
    if recent_high <= 0:
        return PullbackResult(recent_high, cp, None, evaluable=False, in_pullback=False)
    drop_pct = (recent_high - cp) / recent_high
    in_pullback = min_drop <= drop_pct <= max_drop
    return PullbackResult(recent_high, cp, drop_pct, evaluable=True, in_pullback=bool(in_pullback))
