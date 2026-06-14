"""환경설정. .env 파일 또는 환경변수에서 값을 읽습니다."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Supabase ---
    supabase_url: str = ""
    supabase_service_key: str = ""  # 서버 전용 service_role 키 (절대 클라이언트 노출 금지)

    # --- 한국투자증권(KIS) ---
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_account_no: str = ""
    kis_is_paper: bool = True  # True=모의투자, False=실전

    # --- 앱 ---
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
