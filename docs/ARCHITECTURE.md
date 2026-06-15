# 아키텍처

## 디렉토리 구조

```
kestrel/
├── docker-compose.yml          # 단일 VM 배포: 세 서비스 한 번에
├── pyproject.toml              # uv 가상 워크스페이스 루트
├── uv.lock                     # 파이썬 의존성 잠금
├── Makefile                    # make api/engine/frontend/up/test
├── packages/
│   └── broker-client/          # 증권사 추상 인터페이스 + KIS 해외주식 구현 (api·engine 공유)
├── api/                        # FastAPI · /health · Supabase 클라 · 테스트
├── engine/                     # 매매 엔진 워커 · 감시 루프 · SIGTERM 안전종료
└── frontend/                   # Next.js+TS · SSR · Supabase ssr 헬퍼
```

## 패턴

- **3서비스 분리.** frontend(표시) / api(요청-응답) / engine(상시 워커)가 각자 독립 프로세스로 돈다.
- **상태는 DB로 공유.** 서비스끼리 직접 부르지 않는다. 모든 상태는 Supabase에 쓰고 읽는다. (예외: frontend → api 요청)
- **api는 요청-응답 전용.** 들어온 요청을 처리하고 쉰다. 상시 루프를 두지 않는다.
- **engine은 상시 루프.** 아무도 부르지 않아도 혼자 돌며 시세를 보고 복합 지표를 평가한다. 자동매매의 심장.
- **증권사는 broker-client 하나.** api·engine 모두 packages/broker-client(추상 인터페이스)만 import 한다. 구현체는 KIS 해외주식이지만 호출부는 인터페이스에만 의존한다.

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
  ├─ Supabase에서 활성 워치리스트·포지션 상태 로드
  ├─ packages/broker-client(KIS 해외주식)로 시세 조회
  ├─ 복합 지표 평가 (이동평균 20/60 · RSI · 볼린저 · MACD)
  │    ├─ 추세 필터 통과 → 눌림목 → 반등 신호 2개 이상 → 분할매수 단계 판단
  │    └─ 보유 포지션은 익절/손절·60일선 이탈 청산 판단
  ├─ 충족 시 → packages/broker-client(KIS 해외주식)로 모의투자(paper) 주문
  └─ 결과·분할매수 단계·평단가·목표가/손절가를 Supabase에 기록 (orders·positions 테이블)
                    │
                    ▼
        frontend가 SSR로 결과 표시 / 알림
```

핵심: engine과 frontend는 서로를 모른다. 둘 다 Supabase만 본다.

## 상태 관리

- **단일 진실 공급원(SSOT): Supabase.** 조건·주문·체결 상태 전부 여기 있다.
- 프론트 서버 상태는 SSR(Server Components / getServerSideProps)로 Supabase에서 직접 읽는다.
- 프론트 클라이언트 로컬 상태는 React state로만 (전역 상태관리 라이브러리 도입은 MVP 범위 밖).

## 상태 추적 (시나리오 1)

시나리오 1은 분할매수·익절/손절을 다루므로 포지션의 진행 상태를 DB에 추적해야 한다. 구체적 스키마/DDL은 별도 단계에서 정하되, **방향**만 적어둔다:

- `positions` (또는 유사) 테이블에 분할매수 단계(예: 1/3·2/3·3/3), 평단가, 목표가(익절), 손절가, 진입 자격을 통과한 시점 등의 상태 컬럼이 필요하다.
- 분할매수 단계와 평단가는 추가 매수마다 갱신되므로, engine이 다음 루프에서 같은 포지션을 중복 진입하지 않게 멱등하게 다뤄야 한다.

> 위는 설계 방향이다. 이 문서 단계에서 실제 테이블/컬럼을 만들지 않는다.

## 증권사 연동 (KIS 해외주식)

- 증권사는 한국투자(KIS) 해외주식 Open API(REST + WebSocket)이고, 거래 대상은 미국 주식이다(docs/ADR.md ADR-010). 모의투자는 KIS 해외주식 모의(해외 리그) 계좌가 기본(paper)이다.
- 구현 방향으로 커뮤니티 라이브러리 [python-kis](https://github.com/Soju06/python-kis)(국내/해외 통합 인터페이스, 자동 재연결·토큰 관리)를 검토한다. 실제 도입 여부·범위는 코드 단계에서 결정하며, 어느 쪽이든 broker-client 인터페이스 뒤에 둔다(api·engine은 KIS/python-kis를 직접 모른다).
- **운영 시간대 주의**: 미국 정규장은 한국 새벽(대략 23:30~06:00, 미국 서머타임 시 22:30~05:00)이다. engine이 그 시간대에 가동돼 있어야 하고, **서머타임(DST) 전환을 처리**한다 — 고정 오프셋 금지, 미국 동부 시간 기준으로 장 시간을 계산한다.

## 주의

- 새 테이블/컬럼이 필요하면 먼저 스키마를 정하고, 그 스키마를 api·engine·frontend 세 곳이 같이 본다. 스키마가 흔들리면 세 군데를 다 고쳐야 한다.
- engine의 루프 주기(polling interval)·종료 처리(SIGTERM)는 안정성에 직결되므로 임의로 바꾸지 않는다.
