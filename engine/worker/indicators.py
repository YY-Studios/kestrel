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

# 시나리오1 3단계 반등 신호 중 하나: RSI 과매도.
RSI_PERIOD = 14
RSI_OVERSOLD = 35.0


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
