-- Kestrel — strategy_settings 테이블 (전략설정 슬라이스)
-- Supabase 대시보드 → SQL Editor 에 붙여 넣고 실행하세요.
-- 시나리오1의 임계값을 화면에서 조절해 저장하는 단일 행(id=1) 테이블.
-- 주의: 이번 단계는 저장까지만 — engine이 이 값을 읽어 매매에 쓰는 연결은 다음 슬라이스.
--
-- 저장 단위는 코드가 쓰는 값과 맞춘다: %는 분수(0.08 = 8%), RSI·개수는 숫자 그대로.

create table if not exists public.strategy_settings (
    id                bigint primary key default 1,
    rsi_threshold     numeric not null default 35,     -- RSI 과매도 기준 (25~45)
    pullback_min      numeric not null default 0.05,   -- 눌림목 최소 하락 (0.02~0.10, 분수)
    pullback_max      numeric not null default 0.10,   -- 눌림목 최대 하락 (0.05~0.20, 분수)
    rebound_required  integer not null default 2,      -- 반등 신호 필요 개수 (1~3)
    take_profit_pct   numeric not null default 0.08,   -- 익절 목표 (0.03~0.15, 분수)
    stop_loss_pct     numeric not null default 0.05,   -- 손절선 (0.01~0.10, 분수, 양수)
    total_capital     numeric not null default 10000,  -- 투자 금액 (100~1,000,000)
    max_positions     integer not null default 3,      -- 최대 보유 종목 (1~5)
    updated_at        timestamptz not null default now(),
    constraint strategy_settings_singleton check (id = 1)  -- 단일 행 강제
);

-- 기본값 seed(현재 전략 기본값). 이미 있으면 건드리지 않는다.
insert into public.strategy_settings (id) values (1)
on conflict (id) do nothing;

-- 비고:
-- - api는 서버 전용 service_role 키로 upsert({id:1, ...}) 한다. 안전 범위(min/max) 검증은
--   api(app/strategy_settings.py)에서도 수행한다(프론트 슬라이더만 믿지 않음).
-- - engine 반영(이 값을 읽어 evaluate_entry/주문에 주입)은 다음 슬라이스에서 연결한다.
