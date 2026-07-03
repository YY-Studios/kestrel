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

export interface StrategyInfo {
  is_paper: boolean;
  watchlist_count: number;
}

export interface DashboardResponse {
  positions: PositionsSummary;
  watchlist_summary: WatchlistSummary;
  account: Unavailable;
  market: Unavailable;
  calendar: Unavailable;
  strategy: StrategyInfo;
}
