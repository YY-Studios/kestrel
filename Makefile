.PHONY: help install api engine frontend up down test lock

help:
	@echo "install   - 파이썬(uv) + 프론트(pnpm) 의존성 설치"
	@echo "api       - API 서버 로컬 실행 (http://localhost:8000)"
	@echo "engine    - 매매 엔진 워커 로컬 실행"
	@echo "frontend  - 프론트엔드 로컬 실행 (http://localhost:3000)"
	@echo "up        - docker compose 로 전체 기동"
	@echo "down      - docker compose 정지"
	@echo "test      - 파이썬 테스트 실행"
	@echo "lock      - uv.lock / pnpm-lock 갱신"

install:
	uv sync
	cd frontend && pnpm install

api:
	cd api && uv run uvicorn app.main:app --reload --port 8000

engine:
	cd engine && uv run python -m worker.main

frontend:
	cd frontend && pnpm dev

up:
	docker compose up --build

down:
	docker compose down

test:
	uv run --package kestrel-api pytest api/tests

lock:
	uv lock
	cd frontend && pnpm install
