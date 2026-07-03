// 워치리스트 응답 타입 — api(FastAPI) GET /api/watchlist 의 계약.
// api가 Supabase(watchlist + signal_log 최신 1건)를 조합해 내려준다.

export type Decision = "enter" | "wait" | "unevaluable";

export interface WatchlistItem {
  exchange: string;
  symbol: string;
  has_signal: boolean;
  decision: Decision | null;
  trend_ok: boolean | null;
  rsi: number | null;
  bollinger_signal: boolean | null;
  macd_signal: boolean | null;
  rebound_count: number | null;
  rebound_required: number | null;
  updated_at: string | null;
}

export interface WatchlistResponse {
  count: number;
  items: WatchlistItem[];
}
