"""미국 정규장 시간 판정 — 순수 함수, 네트워크 없음.

America/New_York 기준 월~금 **09:30~16:00**을 정규장으로 본다. 서머타임(DST)은 zoneinfo가
자동 처리하므로 한국 시간으로 하드코딩하지 않는다(같은 UTC라도 여름/겨울에 ET가 다름).
공휴일은 이번 범위 밖(정규장 시간만 판정 — 공휴일엔 장중으로 잘못 볼 수 있으나 시세 조회가
실패하면 기존 종목 건너뛰기로 안전).

입력 datetime은 tz-aware여야 한다(main은 datetime.now(timezone.utc) 주입).
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MARKET_OPEN = dtime(9, 30)
MARKET_CLOSE = dtime(16, 0)


def is_market_open(now: datetime) -> bool:
    """now(tz-aware) 기준 미국 정규장 개장 여부. 월~금 & 09:30 ≤ ET < 16:00."""
    et = now.astimezone(ET)
    if et.weekday() >= 5:  # 토(5)·일(6)
        return False
    return MARKET_OPEN <= et.time() < MARKET_CLOSE


def next_market_open(now: datetime) -> datetime:
    """now 이후 다음 정규장 개장 시각(ET 09:30). 장전 평일이면 오늘, 아니면 다음 평일.

    날짜 단위로 다음 개장일을 구한 뒤 그 날짜의 09:30 ET로 조립한다(DST 안전 — date에는
    시각이 없어 timedelta 가산이 벽시계를 어긋내지 않는다).
    """
    et = now.astimezone(ET)
    day = et.date()
    open_today = et.weekday() < 5 and et.time() < MARKET_OPEN
    if not open_today:
        day += timedelta(days=1)
        while day.weekday() >= 5:  # 주말 건너뜀
            day += timedelta(days=1)
    return datetime.combine(day, MARKET_OPEN, tzinfo=ET)


def seconds_until_open(now: datetime) -> float:
    """now에서 다음 개장까지 남은 초(로그용, 대략)."""
    return (next_market_open(now) - now).total_seconds()


def _today_open(now: datetime) -> datetime:
    """now가 속한 날짜의 개장 시각(ET 09:30). 장중 판정과 함께 버퍼 계산에 쓴다."""
    et = now.astimezone(ET)
    return datetime.combine(et.date(), MARKET_OPEN, tzinfo=ET)


def is_tradable(now: datetime, open_buffer_min: float = 0) -> bool:
    """정규장 개장 + 개장 후 open_buffer_min분 경과 여부. 개장 직후 버퍼 구간이면 False.

    개장 직후(밤새 뉴스·주문 반영)의 큰 변동성 구간을 피한다. open_buffer_min<=0이면
    is_market_open과 동일(버퍼 없음). 장외면 항상 False.
    """
    if not is_market_open(now):
        return False
    if open_buffer_min <= 0:
        return True
    return (now - _today_open(now)) >= timedelta(minutes=open_buffer_min)


def seconds_until_tradable(now: datetime, open_buffer_min: float = 0) -> float:
    """폴링 재개까지 남은 초(로그용). 버퍼 구간이면 재개 시각까지, 장외면 다음 개장까지."""
    if not is_market_open(now):
        return seconds_until_open(now)
    resume = _today_open(now) + timedelta(minutes=open_buffer_min)
    return max(0.0, (resume - now).total_seconds())
