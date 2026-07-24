"""Kestrel API 서버 진입점.

프론트엔드(Next.js)가 호출하는 HTTP API. 매매 엔진(워커)과는 별도 프로세스이며,
공통 데이터는 Supabase를 통해 주고받습니다. 지금은 /health 만 살아 있습니다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.alerts import router as alerts_router
from app.config import get_settings
from app.dashboard import router as dashboard_router
from app.orders import router as orders_router
from app.positions import router as positions_router
from app.strategy_settings import router as strategy_settings_router
from app.watchlist import router as watchlist_router

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


app.include_router(watchlist_router)   # GET /api/watchlist
app.include_router(dashboard_router)  # GET /api/dashboard
app.include_router(positions_router)  # GET /api/positions
app.include_router(orders_router)     # GET /api/orders
app.include_router(strategy_settings_router)  # GET·POST /api/strategy-settings
app.include_router(alerts_router)     # GET /api/alerts
