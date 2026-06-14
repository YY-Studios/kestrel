"""워커 환경설정. .env 파일 또는 환경변수에서 읽습니다."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Supabase ---
    supabase_url: str = ""
    supabase_service_key: str = ""

    # --- 한국투자증권(KIS) ---
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_account_no: str = ""
    kis_is_paper: bool = True

    # --- 루프 ---
    poll_interval_seconds: float = 5.0  # 조건 감시 주기


@lru_cache
def get_settings() -> Settings:
    return Settings()
