# 아키텍처

## 디렉토리 구조

```
kestrel/
├── docker-compose.yml          # 단일 VM 배포: 세 서비스 한 번에
├── pyproject.toml              # uv 가상 워크스페이스 루트
├── uv.lock                     # 파이썬 의존성 잠금
├── Makefile                    # make api/engine/frontend/up/test
├── packages/
│   └── kis-client/             # KIS REST 클라이언트 (api·engine 공유)
├── api/                        # FastAPI · /health · Supabase 클라 · 테스트
├── engine/                     # 매매 엔진 워커 · 감시 루프 · SIGTERM 안전종료
└── frontend/                   # Next.js+TS · SSR · Supabase ssr 헬퍼
```

## 패턴

- **3서비스 분리.** frontend(표시) / api(요청-응답) / engine(상시 워커)가 각자 독립 프로세스로 돈다.
- **상태는 DB로 공유.** 서비스끼리 직접 부르지 않는다. 모든 상태는 Supabase에 쓰고 읽는다. (예외: frontend → api 요청)
- **api는 요청-응답 전용.** 들어온 요청을 처리하고 쉰다. 상시 루프를 두지 않는다.
- **engine은 상시 루프.** 아무도 부르지 않아도 혼자 돌며 시세를 보고 조건을 평가한다. 자동매매의 심장.
- **KIS는 공용 클라이언트 하나.** api·engine 모두 packages/kis-client만 import 한다.

## 데이터 흐름

두 개의 독립된 흐름이 Supabase를 통해 만난다.

**1. 설정 흐름 (사람이 트리거)**
```
사용자 → frontend (Next.js) → api (FastAPI) → Supabase
         "조건 등록해줘"        검증·저장        conditions 테이블
```

**2. 매매 흐름 (시스템이 자동, 사람 없음)**
```
engine 워커 (상시 루프)
  ├─ Supabase에서 활성 조건 로드
  ├─ packages/kis-client로 시세 조회
  ├─ 조건 평가
  ├─ 충족 시 → packages/kis-client로 모의투자 주문
  └─ 결과를 Supabase에 기록 (orders 테이블)
                    │
                    ▼
        frontend가 SSR로 결과 표시 / 알림
```

핵심: engine과 frontend는 서로를 모른다. 둘 다 Supabase만 본다.

## 상태 관리

- **단일 진실 공급원(SSOT): Supabase.** 조건·주문·체결 상태 전부 여기 있다.
- 프론트 서버 상태는 SSR(Server Components / getServerSideProps)로 Supabase에서 직접 읽는다.
- 프론트 클라이언트 로컬 상태는 React state로만 (전역 상태관리 라이브러리 도입은 MVP 범위 밖).

## 주의

- 새 테이블/컬럼이 필요하면 먼저 스키마를 정하고, 그 스키마를 api·engine·frontend 세 곳이 같이 본다. 스키마가 흔들리면 세 군데를 다 고쳐야 한다.
- engine의 루프 주기(polling interval)·종료 처리(SIGTERM)는 안정성에 직결되므로 임의로 바꾸지 않는다.
