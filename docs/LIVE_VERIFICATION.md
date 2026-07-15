# LIVE 진입 매수 검증 절차 (통제된 1종목·소액·조건완화)

매매 로직(진입 1·2·3차, 손절, 익절)은 mock까지 검증됐다. 이 문서는 **진입 매수가 실제
KIS 모의(paper) 계좌로 나가는지** 한 번 눈으로 확인하는 절차다. 통제된 상태(1종목·소액·1주)에서,
진입 신호를 인위적으로 띄우기 위해 조건을 **env 완화 프로필**로 임시로 낮춘다.

> ⚠️ **전략 코드의 기본 임계값은 바뀌지 않는다.** 완화는 전부 env로만 주입하고, env를 지우면
> 즉시 평상시 동작으로 복귀한다(코드 원복 불필요). paper 전용 — real 계좌는 코드가 이중 차단한다.

## 안전장치 (변경 없음)

- 실주문은 **`LIVE_ORDERS=true` AND `KIS_IS_PAPER=true`** 일 때만 나간다. 그 외엔 전부 드라이런(로그만).
- `KIS_IS_PAPER=false`(real)이면 `LIVE_ORDERS=true`여도 주문하지 않는다(executor + broker 이중 차단).
- 완화 프로필은 **진입 조건 판단만** 낮춘다. 위 주문 안전장치는 건드리지 않는다.

## 완화 프로필 (env)

`engine/.env` 에 아래 중 하나를 넣는다. **미설정 시 완화 0(평상시 그대로).**

### 방법 1 — 프리셋 한 방 (권장)
```
ENTRY_PROFILE=verify
```
데이터만 충분하면 진입까지 도달하도록 묶어서 완화한다:

| 항목 | 기본값 | verify 프리셋 |
|---|---|---|
| 추세 필터 | SMA20>SMA60 & 가격>SMA60 | **우회(bypass)** |
| 눌림목 하락률 | 5% ~ 10% | **0% ~ 99%** |
| 반등 신호 필요 개수 | 2 / 3 | **1 / 3** |
| RSI 과매도 임계 | 35 | **100 (항상 과매도)** |

### 방법 2 — 개별 완화 (필요한 것만, 프리셋보다 우선)
```
ENTRY_TREND_BYPASS=true      # 추세 필터 우회
ENTRY_REBOUND_REQUIRED=1     # 반등 신호 필요 개수(기본 2)
ENTRY_PULLBACK_MIN_DROP=0.0  # 눌림목 최소 하락률(기본 0.05)
ENTRY_PULLBACK_MAX_DROP=0.99 # 눌림목 최대 하락률(기본 0.10)
ENTRY_RSI_THRESHOLD=100      # RSI 과매도 임계(기본 35)
```
완화가 하나라도 켜지면 워커 시작 로그에 `⚠️ 검증 프로필 활성` 배너가 크게 뜬다.

## 통제 수단

- **1종목만**: `engine/.env` 에 `WATCHLIST=NAS:AAPL` 로 폴백 종목을 한정하거나, Supabase
  `watchlist` 테이블에서 검증 대상 1종목만 `enabled=true`, 나머지 `enabled=false` 로 둔다.
  (DB 워치리스트가 비거나 실패할 때만 `WATCHLIST` env 폴백이 쓰인다.)
- **소액(1~2주)**: `TOTAL_CAPITAL` 을 작게 준다.
  1차 수량 = `floor( (TOTAL_CAPITAL / 3 × 0.40) / 현재가 )` 이므로 **1주 ≈ 현재가 × 7.5**.
  예: AAPL 현재가 $210 → `TOTAL_CAPITAL=1600` 이면 1주. 너무 작으면 "수량 0" 으로 주문이 안 나간다.

## 절차

### 1) 드라이런으로 완화 신호부터 확인 (실주문 없음)
`engine/.env` 에 `ENTRY_PROFILE=verify` + `WATCHLIST=1종목` 만 넣고 (`LIVE_ORDERS` 는 **넣지 않음**):
```
make engine
```
로그에서 확인할 것:
- `⚠️ 검증 프로필 활성 — 진입 조건이 완화됨: ...` 배너
- `주문모드=DRYRUN`
- 대상 종목에 `진입신호 ✓` 그리고 `주문 예정(드라이런) ... 실제 주문 안 나감`
- 만약 `수량 0` 이 뜨면 `TOTAL_CAPITAL` 을 위 공식대로 키운다.

여기까지 신호가 뜨면 완화 프로필이 동작하는 것이다. **다음 단계는 실제 주문이 나간다.**

### 2) 미국장 열렸는지 확인
현재가·일봉이 실시간으로 갱신되는 장중이어야 체결까지 관찰하기 쉽다.
```
make check-price SYMBOL=AAPL
```

### 3) LIVE 실행 (모의계좌 실주문)
`engine/.env` 에 아래를 **모두** 둔 상태로:
```
KIS_IS_PAPER=true            # (필수) 모의계좌 — real 아님
LIVE_ORDERS=true             # 실주문 스위치
ENTRY_PROFILE=verify         # 완화
WATCHLIST=NAS:AAPL           # 1종목
TOTAL_CAPITAL=1600           # 소액(1주 수준, 현재가에 맞게)
```
```
make engine
```
로그에서 `주문모드=LIVE` 와 `실주문 전송(LIVE): NAS→NASD/AAPL 1주 매수 ... ODNO=...` 확인.
1주 체결을 확인했으면 **Ctrl+C 로 즉시 멈춘다**(중복 진입 방지 — 같은 세션 재발주는 막히지만 종료가 깔끔).

### 4) 결과 확인 (여러 경로로 교차 확인)
- **KIS 모바일/HTS 앱** — 모의투자 해외주식 체결/잔고에 AAPL 1주.
- `make check-positions` — positions 테이블 status=open 에 AAPL.
- `make check-orders` — orders 테이블에 buy_1 submitted 기록.
- `make check-balance` — 모의계좌 보유종목/평가.
- **대시보드**(frontend) — 예수금·평가자산·보유종목 반영.

## 5) 원복 체크리스트 (검증 끝나고 반드시)

- [ ] `engine/.env` 에서 `ENTRY_PROFILE` **및** 개별 완화 env(`ENTRY_TREND_BYPASS`,
      `ENTRY_REBOUND_REQUIRED`, `ENTRY_PULLBACK_MIN_DROP`, `ENTRY_PULLBACK_MAX_DROP`,
      `ENTRY_RSI_THRESHOLD`) 전부 삭제/주석.
- [ ] `LIVE_ORDERS` 삭제/주석 (다시 드라이런 기본).
- [ ] `WATCHLIST` env 폴백 제거, Supabase `watchlist` `enabled` 를 원래대로.
- [ ] `TOTAL_CAPITAL` 을 원래 운용값으로.
- [ ] `KIS_IS_PAPER=true` 유지 확인.
- [ ] 검증으로 생긴 AAPL 모의 포지션 정리(원하면 앱/스크립트로 매도) — 이후 자동매매에 섞이지 않게.
- [ ] `make engine` 재기동 시 `⚠️ 검증 프로필 활성` 배너가 **안 뜨는지**, `주문모드=DRYRUN` 인지 확인.
- [ ] `make test` 통과(완화 미설정 시 기본 동작이 테스트로 고정돼 있음).

> 완화는 코드가 아니라 env에만 있으므로, 위 env만 지우면 전략은 즉시 원래 임계값으로 돌아간다.
