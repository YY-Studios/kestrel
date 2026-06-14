"""Kestrel API 서버 진입점.

프론트엔드(Next.js)가 호출하는 HTTP API. 매매 엔진(워커)과는 별도 프로세스이며,
공통 데이터는 Supabase를 통해 주고받습니다. 지금은 /health 만 살아 있습니다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

settings = get_settings()

app = FastAPI(title="Kestrel API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """헬스체크. 서비스가 살아있고 어떤 모드인지 알려줍니다."""
    return {
        "status": "ok",
        "service": "api",
        "kis_paper": settings.kis_is_paper,
    }


# TODO: 여기서부터 라우터를 붙여 나가세요.
#   - app.include_router(strategies.router)  # 전략 CRUD
#   - app.include_router(orders.router)       # 주문 조회
