-- Kestrel — orders 테이블 (Supabase 연동 슬라이스 4)
-- Supabase 대시보드 → SQL Editor 에 붙여 넣고 실행하세요.
-- 개별 주문/체결 내역. positions(현재 보유 상태)와 달리 orders는 매매 한 건 한 건의
-- 역사 기록이다(갱신 아닌 누적). 매매 내역 화면·손절익절 분석의 소스가 된다.

create table if not exists public.orders (
    id               bigint generated always as identity primary key,
    exchange         text not null,            -- NASD / NYSE / AMEX (주문 거래소)
    symbol           text not null,            -- 예: AAPL
    side             text not null,            -- buy / sell
    quantity         integer not null,
    price            double precision,         -- 체결가 또는 주문 지정가
    order_type       text,                     -- buy_1 / buy_2 / buy_3 / sell_tp / sell_sl 등 구분
    broker_order_id  text,                     -- KIS 주문번호(ODNO)
    status           text not null default 'submitted',  -- submitted / filled / rejected
    realized_pnl     double precision,         -- 매도 시 실현 손익(매수는 null)
    reason           text,                     -- 진입/청산 근거
    created_at       timestamptz not null default now()
);

create index if not exists orders_symbol_created_idx
    on public.orders (symbol, created_at desc);
create index if not exists orders_created_idx
    on public.orders (created_at desc);

-- 비고:
-- - engine은 service_role 키로 접근하므로 RLS는 MVP에서 필수가 아니다.
-- - orders는 누적 기록 — 한 번 쓴 행을 갱신하지 않는다(상태 전이가 필요하면 새 행 또는 status 갱신은 다음 단계에서 결정).
