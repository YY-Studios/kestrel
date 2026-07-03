// 대시보드 응답 타입 — api(FastAPI) GET /api/dashboard 계약.
// available=false인 섹션은 아직 미구현(broker 미연결·외부 API 없음) — 가짜 숫자 표시 금지.

export interface PositionItem {
  symbol: string;
  exchange: string;
  avg_price: number | null;
  quantity: number | null;
  tranche_stage: number | null;
  target_price: number | null;
  stop_price: number | null;
  current_price: number | null;  // broker 미연결 시 null
  pnl_pct: number | null;        // broker 미연결 시 null
}

export interface PositionsSummary {
  available: true;
  held: number;
  limit: number;
  items: PositionItem[];
}

export interface WatchlistSummary {
  available: true;
  total: number;
  trend_pass: number;
  near_signal: number;
  enter_count: number;
}

export interface Unavailable {
  available: false;
}

export interface AccountInfo {
  available: true;
  deposit: number | null;      // 예수금(주문가능 외화현금)
  eval_amount: number | null;  // 보유주식 평가금액 합계
  total_asset: number | null;  // 총평가자산(예수금 + 평가)
  pnl_amount: number | null;   // 총평가손익
  pnl_pct: number | null;      // 수익률
  currency: string | null;     // "USD"
}

export interface StrategyInfo {
  is_paper: boolean;
  watchlist_count: number;
}

export interface DashboardResponse {
  positions: PositionsSummary;
  watchlist_summary: WatchlistSummary;
  account: AccountInfo | Unavailable;
  market: Unavailable;
  calendar: Unavailable;
  strategy: StrategyInfo;
}
