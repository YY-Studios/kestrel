# 🦅 Kestrel

한국투자증권(KIS) Open API 기반 개인 자동매매 시스템. 현재는 **부팅되는 스켈레톤** — 세 서비스가 살아서 헬스체크에 응답하고, 안은 `TODO`로 비어 있습니다.

| 서비스 | 스택 | 역할 |
|--------|------|------|
| `frontend` | Next.js + TS (SSR) | 대시보드 |
| `api` | FastAPI | HTTP API |
| `engine` | Python 워커 | 상시 조건 감시·주문 (자동매매 핵심) |
| `packages/kis-client` | Python lib | KIS REST 클라이언트 (api·engine 공용) |

데이터/인증 **Supabase** · 증권사 **KIS REST** · 배포 **Docker + 단일 VM**. 설계 배경은 [`docs/`](docs/)(PRD·ARCHITECTURE·ADR·UI_GUIDE) 참고.

## 빠른 시작
```bash
cp api/.env.example api/.env && cp engine/.env.example engine/.env && cp frontend/.env.example frontend/.env
make install   # 의존성 (uv + pnpm)
make up        # docker compose 로 세 서비스 기동
```
개별 실행: `make api` (:8000) · `make engine` · `make frontend` (:3000) · `make test`

동작 확인: `GET :8000/health` → `{"status":"ok"}`, `:3000` 에 API online 표시.

## 다음에 채울 것
`kis-client`(토큰·시세) → Supabase 스키마(conditions·orders) → `engine` 루프(조건→주문→기록) → `api` 라우터 → `frontend` 대시보드.
