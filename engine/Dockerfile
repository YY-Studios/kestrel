# build context = 레포 루트 (워크스페이스 전체가 필요하므로)
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY engine ./engine

RUN uv sync --frozen --package kestrel-engine --no-dev

WORKDIR /app/engine
CMD ["uv", "run", "--no-dev", "python", "-m", "worker.main"]
