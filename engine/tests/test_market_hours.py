"""미국 정규장 시간 판정 테스트 — 요일·경계·서머타임(DST). 실네트워크 0.

America/New_York 기준 월~금 09:30~16:00. DST는 zoneinfo가 자동 처리하므로,
UTC 같은 시각이라도 여름(EDT, UTC-4)·겨울(EST, UTC-5)에 ET가 달라지는지로 검증한다.
공휴일은 이번 범위 밖(정규장 시간만).
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from worker.market_hours import is_market_open, next_market_open, seconds_until_open

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


def _et(y, mo, d, h, mi) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=ET)


# --- 요일 / 시간대 ---------------------------------------------------------

def test_weekday_midday_open() -> None:
    assert is_market_open(_et(2026, 7, 23, 10, 0)) is True  # 목요일 10:00


def test_weekday_evening_closed() -> None:
    assert is_market_open(_et(2026, 7, 23, 20, 0)) is False  # 목요일 저녁


def test_weekday_early_morning_closed() -> None:
    assert is_market_open(_et(2026, 7, 23, 6, 0)) is False


def test_saturday_closed() -> None:
    assert is_market_open(_et(2026, 7, 25, 10, 0)) is False  # 토


def test_sunday_closed() -> None:
    assert is_market_open(_et(2026, 7, 26, 10, 0)) is False  # 일


# --- 경계 (09:30 포함, 16:00 제외) ----------------------------------------

def test_boundary_open_edges() -> None:
    assert is_market_open(_et(2026, 7, 23, 9, 29)) is False
    assert is_market_open(_et(2026, 7, 23, 9, 30)) is True
    assert is_market_open(_et(2026, 7, 23, 15, 59)) is True
    assert is_market_open(_et(2026, 7, 23, 16, 0)) is False


# --- 서머타임: 같은 UTC라도 여름/겨울에 ET가 다름 --------------------------

def test_dst_summer_edt() -> None:
    # 여름 EDT(UTC-4): 14:00 UTC = 10:00 ET(개장), 13:00 UTC = 09:00 ET(장전)
    assert is_market_open(datetime(2026, 7, 23, 14, 0, tzinfo=UTC)) is True
    assert is_market_open(datetime(2026, 7, 23, 13, 0, tzinfo=UTC)) is False


def test_dst_winter_est() -> None:
    # 겨울 EST(UTC-5): 15:00 UTC = 10:00 ET(개장), 14:00 UTC = 09:00 ET(장전)
    assert is_market_open(datetime(2026, 1, 23, 15, 0, tzinfo=UTC)) is True
    assert is_market_open(datetime(2026, 1, 23, 14, 0, tzinfo=UTC)) is False


def test_dst_same_utc_differs_by_season() -> None:
    # 13:30 UTC: 여름엔 09:30 ET(개장), 겨울엔 08:30 ET(장전) — DST 자동 반영 증거
    assert is_market_open(datetime(2026, 7, 23, 13, 30, tzinfo=UTC)) is True
    assert is_market_open(datetime(2026, 1, 23, 13, 30, tzinfo=UTC)) is False


# --- 다음 개장 시각 --------------------------------------------------------

def test_next_open_before_today_open() -> None:
    # 평일 장전(08:00) → 오늘 09:30
    assert next_market_open(_et(2026, 7, 23, 8, 0)) == _et(2026, 7, 23, 9, 30)


def test_next_open_after_close_is_next_weekday() -> None:
    # 목요일 20:00 → 금요일 09:30
    assert next_market_open(_et(2026, 7, 23, 20, 0)) == _et(2026, 7, 24, 9, 30)


def test_next_open_friday_evening_to_monday() -> None:
    # 금요일 20:00 → 월요일 09:30(주말 건너뜀)
    assert next_market_open(_et(2026, 7, 24, 20, 0)) == _et(2026, 7, 27, 9, 30)


def test_next_open_saturday_to_monday() -> None:
    assert next_market_open(_et(2026, 7, 25, 12, 0)) == _et(2026, 7, 27, 9, 30)


def test_seconds_until_open_positive_when_closed() -> None:
    secs = seconds_until_open(_et(2026, 7, 23, 8, 0))
    assert secs == 90 * 60  # 08:00 → 09:30 = 90분
