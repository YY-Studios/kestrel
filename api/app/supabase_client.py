"""Supabase 클라이언트 (서버용).

service_role 키를 쓰므로 RLS를 우회합니다 — 서버에서만 사용하세요.
설정이 비어 있으면 첫 호출 시 에러가 납니다(스켈레톤 단계에서는 정상).
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def get_supabase() -> Client:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_key:
        raise RuntimeError(
            "Supabase 설정이 비어 있습니다. api/.env 에 SUPABASE_URL / "
            "SUPABASE_SERVICE_KEY 를 채우세요."
        )
    return create_client(s.supabase_url, s.supabase_service_key)
