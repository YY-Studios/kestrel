"""Supabase 접근 — engine 전용, 한 곳에 캡슐화.

서버 전용 service(secret) 키로만 접근한다(SUPABASE_SERVICE_KEY). 키는 .env에서만 읽고
코드·로그에 노출하지 않는다. KIS 연동(broker-client)과 마찬가지로 외부 I/O를 이 모듈에 가둔다.

이번 슬라이스: 연결 + watchlist 테이블 read + 안전 폴백. 주문·포지션·신호로그는 다음 슬라이스.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from worker.config import Settings, get_settings

if TYPE_CHECKING:
    from worker.indicators import EntryResult

logger = logging.getLogger("kestrel.engine")

WATCHLIST_TABLE = "watchlist"
SIGNAL_LOG_TABLE = "signal_log"
# 신호 로그를 "변화 시에만" 기록할 때 비교하는 핵심 필드(연속값 pullback_pct·rsi는 제외 — 스팸 방지).
_SIGNAL_KEY_FIELDS = ("decision", "trend_ok", "rebound_count", "evaluable")


class SupabaseLike(Protocol):
    def table(self, name: str) -> Any: ...


def make_client(url: str, service_key: str) -> Any:
    """URL·service 키로 Supabase 클라이언트 생성. 값이 비면 친절한 에러(값은 출력 안 함)."""
    if not url or not service_key:
        raise RuntimeError(
            "Supabase 연결 정보가 없습니다. engine/.env 에 "
            "SUPABASE_URL · SUPABASE_SERVICE_KEY 를 채우세요."
        )
    from supabase import create_client  # 지연 import — 모듈 로드 시 패키지/네트워크 비의존

    return create_client(url, service_key)


def get_client(settings: Settings | None = None) -> Any:
    """설정(.env)에서 Supabase 클라이언트를 만든다."""
    settings = settings or get_settings()
    return make_client(settings.supabase_url, settings.supabase_service_key)


def get_watchlist(client: SupabaseLike) -> list[tuple[str, str]]:
    """watchlist 테이블에서 활성 종목을 (거래소, 종목) 목록으로. 거래소/종목은 대문자."""
    resp = (
        client.table(WATCHLIST_TABLE)
        .select("exchange,symbol")
        .eq("enabled", True)
        .order("symbol")
        .execute()
    )
    rows = getattr(resp, "data", None) or []
    out: list[tuple[str, str]] = []
    for row in rows:
        exchange = (row.get("exchange") or "").strip().upper()
        symbol = (row.get("symbol") or "").strip().upper()
        if exchange and symbol:
            out.append((exchange, symbol))
    return out


def load_watchlist(
    client: SupabaseLike, default: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """DB에서 워치리스트를 읽되, 비었거나 실패하면 default로 폴백한다(루프가 죽지 않게)."""
    try:
        rows = get_watchlist(client)
    except Exception as exc:  # 연결/쿼리 오류 — 폴백
        logger.warning("워치리스트 로드 실패(%s) — 폴백 워치리스트 사용", type(exc).__name__)
        return default
    if not rows:
        logger.warning("DB 워치리스트가 비어 있음 — 폴백 워치리스트 사용")
        return default
    return rows


# --- 신호 로그 (판단 기록) -------------------------------------------------

def entry_result_to_record(exchange: str, symbol: str, result: "EntryResult") -> dict[str, Any]:
    """EntryResult를 signal_log 한 행(dict)으로 변환."""
    decision = "enter" if result.enter else ("wait" if result.evaluable else "unevaluable")
    return {
        "exchange": exchange,
        "symbol": symbol,
        "decision": decision,
        "trend_ok": bool(result.trend.passed),
        "pullback_pct": result.pullback.drop_pct,
        "rebound_count": result.rebound_count,
        "rebound_required": result.rebound_required,
        "rsi": result.rsi.value,
        "bollinger_signal": bool(result.bollinger.signal),
        "macd_signal": bool(result.macd.rebound),
        "evaluable": bool(result.evaluable),
    }


def insert_signal_log(client: Any, record: dict[str, Any]) -> None:
    """signal_log 테이블에 한 행 삽입."""
    client.table(SIGNAL_LOG_TABLE).insert(record).execute()


def _signal_changed(prev: dict[str, Any], new: dict[str, Any]) -> bool:
    """핵심 필드(decision·trend_ok·rebound_count·evaluable) 중 하나라도 다르면 변화로 본다."""
    return any(prev.get(k) != new.get(k) for k in _SIGNAL_KEY_FIELDS)


class SignalRecorder:
    """판단을 signal_log에 기록하되 **의미 있는 변화 시에만** 쓴다(스팸 방지).

    종목별 직전 기록 상태를 메모리에 들고, 핵심 필드가 바뀌었을 때(또는 첫 관측)만 insert.
    DB 쓰기 실패는 매매/판단을 막지 않는다 — 경고만 남기고 진행(보조 기록).
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._last: dict[str, dict[str, Any]] = {}

    def record_if_changed(self, exchange: str, symbol: str, result: "EntryResult") -> bool:
        """변화가 있으면 기록하고 True, 변화 없거나 기록 실패면 False."""
        record = entry_result_to_record(exchange, symbol, result)
        key = f"{exchange}/{symbol}"
        prev = self._last.get(key)
        if prev is not None and not _signal_changed(prev, record):
            return False  # 변화 없음 → 기록 생략
        try:
            insert_signal_log(self._client, record)
        except Exception as exc:  # 보조 기록 — 실패해도 루프는 계속
            logger.warning("신호 로그 기록 실패 %s (%s) — 계속", key, type(exc).__name__)
            return False  # 실패 시 직전 상태 미갱신 → 다음에 다시 시도
        self._last[key] = record
        return True
