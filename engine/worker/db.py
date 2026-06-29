"""Supabase 접근 — engine 전용, 한 곳에 캡슐화.

서버 전용 service(secret) 키로만 접근한다(SUPABASE_SERVICE_KEY). 키는 .env에서만 읽고
코드·로그에 노출하지 않는다. KIS 연동(broker-client)과 마찬가지로 외부 I/O를 이 모듈에 가둔다.

이번 슬라이스: 연결 + watchlist 테이블 read + 안전 폴백. 주문·포지션·신호로그는 다음 슬라이스.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from worker.config import Settings, get_settings

logger = logging.getLogger("kestrel.engine")

WATCHLIST_TABLE = "watchlist"


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


def load_watchlist_or_default(default: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """연결까지 포함해 워치리스트를 안전하게 로드. 연결 실패 시에도 default 폴백."""
    try:
        client = get_client()
    except Exception as exc:
        logger.warning("Supabase 연결 실패(%s) — 폴백 워치리스트 사용", type(exc).__name__)
        return default
    return load_watchlist(client, default)
