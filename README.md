# 🦅 Kestrel

한국투자(KIS) Open API 기반 **미국 주식** 개인 자동매매 시스템. KIS 해외주식 API로 시나리오 1 복합 전략(추세 추종 필터 → 눌림목 반등 → 3회 분할매수 → 익절/손절)을 모의투자(paper, 해외 리그) 계좌에 자동 집행합니다. 복합 지표 판단·분할매수·손절/익절, 화면(대시보드·워치리스트·포지션·매매내역·전략설정), 전략설정의 엔진 반영까지 동작하며, KIS 모의계좌로 **진입 매수 LIVE 검증**을 마쳤습니다.

| 서비스 | 스택 | 역할 |
|--------|------|------|
| `frontend` | Next.js + TS (SSR) | 대시보드 |
| `api` | FastAPI | HTTP API |
| `engine` | Python 워커 | 상시 복합 지표 감시·주문 (자동매매 핵심) |
| `packages/broker-client` | Python lib | 증권사 추상 인터페이스 + KIS 해외주식 구현 (api·engine 공용) |

데이터/인증 **Supabase** · 증권사 **KIS 해외주식 REST+WS** (미국 주식, paper 기본) · 배포 **Docker + 단일 VM**. 미국장이 한국 새벽이라 engine은 새벽 가동·서머타임 처리가 필요합니다. 설계 배경은 [`docs/`](docs/)(PRD·ARCHITECTURE·ADR·UI_GUIDE) 참고.

## 사용법 (실행 명령어)

### 1) 최초 1회 준비
```bash
cp api/.env.example api/.env && cp engine/.env.example engine/.env && cp frontend/.env.example frontend/.env
# → api/.env · engine/.env 에 Supabase URL·키, KIS App Key/Secret/계좌, KIS_IS_PAPER=true 채우기
make install   # 의존성 (uv + pnpm)
```
그다음 Supabase 스키마(아래 SQL) 실행.

### 2) 서비스 기동 (각각 별도 터미널 — 계속 떠 있는 프로세스)
| 명령어 | 결과 |
|--------|------|
| `make api` | API 서버 → http://localhost:8000 |
| `make frontend` | 화면 → http://localhost:3000 |
| `make engine` | 매매 엔진 워커 (상시 감시·주문) |
| `make up` / `make down` | docker로 세 서비스 한 번에 기동 / 정지 |
| `make test` | 전체 테스트 (api · broker-client · engine) |

> api·frontend만 켜면 화면은 다 보입니다. 실제 감시·매매까지 보려면 `make engine`을 추가로 켜세요.
> 동작 확인: `GET :8000/health` → `{"status":"ok"}`.

### 3) 화면 (api + frontend 켠 상태)
| URL | 화면 |
|-----|------|
| http://localhost:3000/dashboard | 대시보드 (자산·손익·요약) |
| http://localhost:3000/watchlist | 워치리스트 |
| http://localhost:3000/positions | 포지션 (보유 상태·손익·청산 거리) |
| http://localhost:3000/orders | 매매 내역 (체결 로그) |
| http://localhost:3000/strategy | 전략 설정 (슬라이더·안전 범위) |

### 4) 수동 확인 스크립트 (실제 KIS/Supabase 조회 — `engine/.env` 필요)
| 명령어 | 확인 내용 |
|--------|-----------|
| `make check-token` | KIS 토큰 발급 |
| `make check-supabase` | Supabase 연결·워치리스트 |
| `make check-price SYMBOL=NVDA` | 현재가 |
| `make check-daily SYMBOL=NVDA` | 일봉(최근 종가) |
| `make check-balance` | 모의계좌 예수금·평가자산·보유 |
| `make check-positions` | 보유 포지션(open) |
| `make check-orders` | 주문/체결 내역 |
| `make check-signal-log` | 판단 기록 |
| `make check-order QTY=1 SIDE=buy` | 모의 1회 주문(확인 프롬프트) |

### 5) 전략설정 반영 확인
`/strategy`에서 슬라이더 조절 → 저장 → `make engine` 재시작 → 시작 로그에 `전략설정 적용: … (출처: DB)` 확인.

### 6) LIVE 진입 검증 (통제된 실주문 — 필요할 때만)
`engine/.env`에 임시로 넣고 `make engine`, 끝나면 **반드시 제거**(원복 체크리스트: [`docs/LIVE_VERIFICATION.md`](docs/LIVE_VERIFICATION.md)):
```
LIVE_ORDERS=true
ENTRY_PROFILE=verify
WATCHLIST_OVERRIDE=NAS:NVDA
TOTAL_CAPITAL=1600
```
`KIS_IS_PAPER=true`(모의)에서만 실주문 나가고 real은 이중 차단됩니다.

## Supabase 스키마
engine이 쓰는 테이블을 Supabase 대시보드 → **SQL Editor**에서 먼저 만드세요:
- [`docs/supabase/watchlist.sql`](docs/supabase/watchlist.sql) — 감시 종목(읽기)
- [`docs/supabase/signal_log.sql`](docs/supabase/signal_log.sql) — 판단 기록(변화 시에만 쓰기)
- [`docs/supabase/positions.sql`](docs/supabase/positions.sql) — 보유 포지션(평단·수량·분할단계·목표/손절)
- [`docs/supabase/orders.sql`](docs/supabase/orders.sql) — 주문/체결 내역(누적, 매매 내역·분석 소스)
- [`docs/supabase/strategy_settings.sql`](docs/supabase/strategy_settings.sql) — 전략 임계값(단일 행, 화면에서 조절→엔진 반영)

확인: `make check-supabase`(연결·watchlist) · `make check-signal-log`(판단) · `make check-positions`(보유) · `make check-orders`(체결 내역). engine/.env의 `SUPABASE_URL`·`SUPABASE_SERVICE_KEY` 필요.
DB가 비었거나 연결이 안 되면 engine은 폴백 워치리스트(`NAS:AAPL`)로 동작하고 신호 로그는 생략합니다(매매는 계속).

## 구현 현황
- ✅ `broker-client` — KIS 해외주식 인증·시세·일봉·주문·잔고 (실서버 검증)
- ✅ 지표·판단 — 추세·눌림목·RSI·볼린저·MACD·진입 종합
- ✅ 매매 로직 — 진입 1·2·3차 분할매수·손절·익절 (청산 우선, 물타기 방지)
- ✅ DB — watchlist·signal_log·positions·orders·strategy_settings
- ✅ 화면 — 대시보드·워치리스트·포지션·매매내역·전략설정
- ✅ 전략설정 → 엔진 반영 (화면 저장값을 시작 시 로드해 판단에 주입)
- ✅ LIVE 진입 검증 — KIS 모의계좌로 실제 진입 매수 확인
- ⏳ 남은 것 — 손절/익절 LIVE 검증 · 손절익절 분석 상세·캘린더·공부·알림 화면 · 새벽 가동/서머타임 운영

## 개발 워크플로우 (Harness)
기획을 `docs/`(PRD·ARCHITECTURE·ADR·UI_GUIDE)에 적고 Claude Code에서 `/harness`를 실행하면, 계획을 Phase·step으로 쪼개 순차 실행하고 step마다 테스트(AC)를 검증한다. 모든 테스트가 통과하면 PR 생성 → 스쿼시 머지 → 위키·README 갱신까지 자동으로 마감한다. 자세한 사용법은 [위키](https://github.com/YY-Studios/kestrel/wiki) 참고.

