"""KIS broker 클라이언트 (api 서버용) — 잔고 등 조회 전용.

증권사 호출은 broker-client(KisClient)만 경유한다(CLAUDE.md). api는 여기서 만든
클라이언트로 읽기 조회(잔고)만 한다. 키는 .env에서만 읽고 코드/로그에 노출하지 않는다.
기본 모의(paper) — kis_is_paper 설정이 도메인/ TR을 결정한다.
"""

from __future__ import annotations

from pathlib import Path

from broker_client import KisClient, KisConfig

from app.config import get_settings

# engine·scripts와 동일한 토큰 캐시 파일을 공유해 재발급(EGW00133)을 피한다(.gitignore됨).
_TOKEN_CACHE = Path(__file__).resolve().parents[2] / ".kis_token_cache.json"


def get_broker() -> KisClient:
    """설정(.env)으로 KisClient를 만든다. 키가 비었으면 첫 호출 시 KIS가 거부한다."""
    s = get_settings()
    return KisClient(
        KisConfig(
            app_key=s.kis_app_key,
            app_secret=s.kis_app_secret,
            account_no=s.kis_account_no,
            is_paper=s.kis_is_paper,
        ),
        token_cache_path=str(_TOKEN_CACHE),
    )
