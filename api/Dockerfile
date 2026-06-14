# build context = 레포 루트 (워크스페이스 전체가 필요하므로)
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# 워크스페이스 매니페스트 + 공용 패키지 + api 소스
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY api ./api

# api 멤버의 의존성만 동기화 (dev 제외)
RUN uv sync --frozen --package kestrel-api --no-dev

WORKDIR /app/api
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
