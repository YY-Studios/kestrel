.PHONY: help install api engine frontend up down test lock check-token check-price check-order

# 수동 확인 스크립트 인자 (override 예: make check-price SYMBOL=TSLA / make check-order QTY=1 SIDE=buy)
SYMBOL ?= AAPL
EXCD ?= NAS        # 시세 조회 거래소 (NAS/NYS/AMS)
ORD_EXCD ?= NASD  # 주문 거래소 (NASD/NYSE/AMEX)
QTY ?= 1
SIDE ?= buy

help:
	@echo "install   - 파이썬(uv) + 프론트(pnpm) 의존성 설치"
	@echo "api       - API 서버 로컬 실행 (http://localhost:8000)"
	@echo "engine    - 매매 엔진 워커 로컬 실행"
	@echo "frontend  - 프론트엔드 로컬 실행 (http://localhost:3000)"
	@echo "up        - docker compose 로 전체 기동"
	@echo "down      - docker compose 정지"
	@echo "test      - 파이썬 테스트 실행"
	@echo "check-token - (수동) 실제 KIS 모의 도메인에 붙어 토큰 발급 확인 (.env 필요)"
	@echo "check-price - (수동) 실제 미국 종목 현재가 조회 확인 (예: make check-price SYMBOL=TSLA)"
	@echo "check-order - (수동) 모의 계좌로 1회 주문 확인, 확인 프롬프트 (예: make check-order QTY=1 SIDE=buy)"
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
	uv run --package kestrel-api pytest packages/broker-client/tests

# 수동 확인용 — 실제 KIS 네트워크를 타므로 test 에 넣지 않는다. engine/.env 필요.
check-token:
	uv run --package kestrel-engine python scripts/check_token.py

check-price:
	uv run --package kestrel-engine python scripts/check_price.py $(SYMBOL) $(EXCD)

# 실주문(모의)을 전송한다 — 확인 프롬프트 있음. test 에 절대 넣지 않는다.
check-order:
	uv run --package kestrel-engine python scripts/check_order.py $(SYMBOL) $(ORD_EXCD) $(QTY) $(SIDE)

lock:
	uv lock
	cd frontend && pnpm install
