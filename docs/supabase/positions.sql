-- Kestrel — positions 테이블 (Supabase 연동 슬라이스 3)
-- Supabase 대시보드 → SQL Editor 에 붙여 넣고 실행하세요.
-- 보유 포지션 상태: 무엇을·얼마에·몇 주·분할 몇 차까지 샀는지 + 목표가/손절가.
-- engine이 held_symbols(보유 종목)·분할 단계·평단(익절손절 기준)을 여기서 읽고 갱신한다.

create table if not exists public.positions (
    id             bigint generated always as identity primary key,
    exchange       text not null,            -- NASD / NYSE / AMEX (주문 거래소)
    symbol         text not null,            -- 예: AAPL
    avg_price      double precision not null,-- 평균 매입 단가
    quantity       integer not null,         -- 보유 수량
    tranche_stage  integer not null default 1, -- 분할매수 단계 (1~3)
    target_price   double precision,         -- 익절 목표가
    stop_price     double precision,         -- 손절가
    status         text not null default 'open',  -- open / closed
    entry_reason   text,                     -- 진입 근거(신호 요약)
    opened_at      timestamptz not null default now(),
    closed_at      timestamptz,              -- 청산 시각(보유 중 null)
    updated_at     timestamptz not null default now()
);

create index if not exists positions_symbol_idx on public.positions (symbol);
create index if not exists positions_status_idx on public.positions (status);

-- 한 종목은 동시에 1개만 "보유 중(open)" — 부분 유니크 인덱스로 강제.
create unique index if not exists positions_one_open_per_symbol
    on public.positions (symbol) where (status = 'open');

-- 비고:
-- - engine은 service_role 키로 접근하므로 RLS는 MVP에서 필수가 아니다.
-- - upsert_position은 위 유니크 인덱스를 전제로 같은 종목의 open 포지션을 갱신한다.
