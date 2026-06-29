-- Kestrel — signal_log 테이블 (Supabase 연동 슬라이스 2)
-- Supabase 대시보드 → SQL Editor 에 붙여 넣고 실행하세요.
-- engine이 시나리오1 판단을 "의미 있는 변화 시에만" 기록한다(매 폴링마다 전부 저장하지 않음).
-- 보조 기록 — 기록 실패가 매매/판단을 막지 않는다. UI 알림·손절분석의 소스가 된다.

create table if not exists public.signal_log (
    id                bigint generated always as identity primary key,
    exchange          text not null,           -- NAS / NYS / AMS
    symbol            text not null,           -- 예: AAPL
    decision          text not null,           -- enter / wait / unevaluable
    trend_ok          boolean,                 -- 1단계 추세 통과
    pullback_pct      double precision,        -- 2단계 고점 대비 하락률(0.08 = 8%)
    rebound_count     integer,                 -- 3단계 반등 신호 충족 개수
    rebound_required  integer,                 -- 필요 개수(기본 2)
    rsi               double precision,
    bollinger_signal  boolean,
    macd_signal       boolean,
    evaluable         boolean,                 -- 판단 가능 여부(데이터 충분)
    note              text,                    -- 선택 메모
    created_at        timestamptz not null default now()
);

create index if not exists signal_log_symbol_created_idx
    on public.signal_log (symbol, created_at desc);

-- 비고:
-- - engine은 service_role 키로 접근하므로 RLS는 MVP에서 필수가 아니다.
-- - "변화 시에만" 기록: decision·trend_ok·rebound_count·evaluable 중 하나라도 바뀌면 새 행.
--   연속값(pullback_pct·rsi)은 변화 판정에 쓰지 않는다(스팸 방지).
