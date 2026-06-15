# 🦅 Kestrel

Alpaca Open API 기반 **미국 주식** 개인 자동매매 시스템. 시나리오 1 복합 전략(추세 추종 필터 → 눌림목 반등 → 3회 분할매수 → 익절/손절)을 모의투자(paper) 계좌에 자동 집행합니다. 현재는 **부팅되는 스켈레톤** — 세 서비스가 살아서 헬스체크에 응답하고, 안은 `TODO`로 비어 있습니다.

| 서비스 | 스택 | 역할 |
|--------|------|------|
| `frontend` | Next.js + TS (SSR) | 대시보드 |
| `api` | FastAPI | HTTP API |
| `engine` | Python 워커 | 상시 복합 지표 감시·주문 (자동매매 핵심) |
| `packages/broker-client` | Python lib | 증권사 추상 인터페이스 + Alpaca 구현 (api·engine 공용) |

데이터/인증 **Supabase** · 증권사 **Alpaca REST+WS** (미국 주식, paper 기본) · 배포 **Docker + 단일 VM**. 설계 배경은 [`docs/`](docs/)(PRD·ARCHITECTURE·ADR·UI_GUIDE) 참고.

## 빠른 시작
```bash
cp api/.env.example api/.env && cp engine/.env.example engine/.env && cp frontend/.env.example frontend/.env
make install   # 의존성 (uv + pnpm)
make up        # docker compose 로 세 서비스 기동
```
개별 실행: `make api` (:8000) · `make engine` · `make frontend` (:3000) · `make test`

동작 확인: `GET :8000/health` → `{"status":"ok"}`, `:3000` 에 API online 표시.

## 다음에 채울 것
`broker-client`(Alpaca 인증·시세·주문) → Supabase 스키마(워치리스트·orders·positions) → `engine` 루프(복합 지표 평가→분할매수→익절/손절→기록) → `api` 라우터 → `frontend` 대시보드.

## 개발 워크플로우 (Harness)
기획을 `docs/`(PRD·ARCHITECTURE·ADR·UI_GUIDE)에 적고 Claude Code에서 `/harness`를 실행하면, 계획을 Phase·step으로 쪼개 순차 실행하고 step마다 테스트(AC)를 검증한다. 모든 테스트가 통과하면 PR 생성 → 스쿼시 머지 → 위키·README 갱신까지 자동으로 마감한다. 자세한 사용법은 [위키](https://github.com/YY-Studios/kestrel/wiki) 참고.

