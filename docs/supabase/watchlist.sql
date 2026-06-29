-- Kestrel — watchlist 테이블 (Supabase 연동 슬라이스 1)
-- Supabase 대시보드 → SQL Editor 에 붙여 넣고 실행하세요.
-- 사람이 직접 채우는 감시 종목 목록. engine이 enabled=true 행을 읽어 시나리오1을 평가합니다.
-- 거래소(exchange)는 시세 계열 코드: NAS(나스닥) / NYS(뉴욕) / AMS(아멕스).

create table if not exists public.watchlist (
    id          bigint generated always as identity primary key,
    exchange    text not null,           -- NAS / NYS / AMS
    symbol      text not null,           -- 예: AAPL
    enabled     boolean not null default true,
    created_at  timestamptz not null default now(),
    unique (exchange, symbol)
);

-- 예시 시드(선택): 원하는 종목으로 바꿔 INSERT.
-- insert into public.watchlist (exchange, symbol) values
--   ('NAS', 'AAPL'),
--   ('NAS', 'TSLA'),
--   ('NAS', 'NVDA')
-- on conflict (exchange, symbol) do nothing;

-- 비고:
-- - engine은 서버 전용 service_role 키로 접근하므로 RLS는 MVP에서 필수가 아니다.
--   (frontend가 직접 이 테이블을 읽게 되면 그때 RLS 정책을 추가한다 — 다음 슬라이스.)
