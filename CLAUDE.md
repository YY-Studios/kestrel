# 프로젝트: Kestrel — 개인 자동매매

조건 기반으로 주식을 자동 매수/매도하는 시스템. 모노레포로 3개 서비스가 함께 산다.

## 기술 스택

- **frontend/** — Next.js + TypeScript (strict), SSR. Supabase ssr 헬퍼로 상태 표시.
- **api/** — FastAPI (Python). 프론트 요청 처리 + Supabase 접근.
- **engine/** — Python 워커. 상시 실행되며 조건 감시 → 주문. FastAPI와 별개 프로세스.
- **packages/kis-client/** — 한국투자(KIS) REST 클라이언트. api·engine이 공유하는 공용 패키지.
- **데이터/인증** — Supabase (PostgreSQL). 세 서비스의 단일 진실 공급원(SSOT).
- **증권사** — 한국투자(KIS) Open API, REST. 모의투자(paper) 기본.
- **빌드/배포** — uv 워크스페이스, Docker Compose, 단일 VM.

## 아키텍처 규칙

- **CRITICAL: 모든 KIS 주문은 모의투자(paper) 모드가 기본값이다.** 실전(real/운영) 계좌로 주문을 보내는 코드는 사용자의 명시적 요청과 승인 없이 생성·수정하지 마라. paper/real 분기가 모호하면 항상 paper로 가정한다.
- **CRITICAL: 매매 엔진(engine/)은 FastAPI 밖의 별도 프로세스다.** api/ 안에서 `while True`, 무한 폴링 루프, 백그라운드 스케줄러, 상시 워커를 만들지 마라. 상시 감시/주문 로직은 전부 engine/에 둔다.
- **CRITICAL: KIS API 호출은 오직 packages/kis-client를 통해서만 한다.** api/나 engine/ 안에서 KIS REST 엔드포인트를 직접 호출하는(requests/httpx로 직접 때리는) 코드를 작성하지 마라. 클라이언트가 두 벌로 갈라지는 것을 막는다.
- **CRITICAL: API 키·시크릿·계좌번호는 .env로만 주입한다.** 코드나 커밋에 절대 하드코딩하지 마라. 새 환경변수가 필요하면 각 서비스의 `.env.example`에 키만(값 없이) 추가한다.
- 서비스 간 상태 공유는 Supabase(DB)를 통한다. 서비스끼리 직접 HTTP로 부르지 마라 (frontend→api 제외).
- 프론트(frontend/)에서 KIS를 직접 호출하지 마라. 반드시 api/를 경유한다.
- 언어 경계를 지켜라: Python은 api/·engine/·packages/, TypeScript는 frontend/. 한쪽 코드가 다른 쪽 폴더로 새지 않게 한다.
- 전역 설정(docker-compose, pyproject 워크스페이스, _document/_app, Next config)을 바꾸기 전에 변경 범위를 먼저 점검한다. 한 줄 바꾸면 세 서비스가 다 영향받을 수 있다.

## 개발 프로세스

- **CRITICAL: 새 기능은 테스트를 먼저 작성하고, 그 테스트를 통과시키는 구현을 작성한다 (TDD).** Python은 pytest, 프론트는 프로젝트 테스트 러너를 쓴다. 특히 조건 평가·주문 로직은 테스트 없이 구현하지 마라.
- 작업 범위를 벗어나지 마라. 지시된 step에 명시된 것만 만들고, "이 기능도 추가할까요" 식으로 scope를 늘리지 마라. (제외 항목은 docs/PRD.md 참고)
- 커밋 메시지는 conventional commits 형식: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- 임시 mock 데이터를 넣었다면 작업 완료 전 100% 제거한다.

## 명령어

```
make install     # uv sync + 프론트 의존성 설치
make up          # docker compose로 세 서비스 한 번에 기동
make api         # FastAPI 단독 실행 → http://localhost:8000/health
make engine      # 매매 엔진 워커 단독 실행
make frontend    # Next.js 단독 실행 → http://localhost:3000
make test        # 전체 테스트 (pytest + 프론트)
```

## 문서 우선순위

작업 전 docs/를 읽어라. 충돌 시 우선순위: **이 파일(CLAUDE.md) > docs/ADR.md > docs/ARCHITECTURE.md > docs/PRD.md > docs/UI_GUIDE.md**.
