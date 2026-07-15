// 포지션 응답 타입 — api(FastAPI) GET /api/positions 계약.
// current_price·손익·거리는 broker(현재가) 조회에 의존 — 실패 시 null(가짜 숫자 금지).

export interface PositionItem {
  symbol: string;
  exchange: string;
  avg_price: number | null;
  quantity: number | null;
  tranche_stage: number | null;
  target_price: number | null;
  stop_price: number | null;
  current_price: number | null;         // 현재가 조회 실패 시 null
  unrealized_pnl: number | null;        // (현재가-평단)×수량
  unrealized_pnl_pct: number | null;    // (현재가-평단)/평단×100
  target_distance_pct: number | null;   // 현재가→목표 (+)
  stop_distance_pct: number | null;     // 현재가→손절 (−)
  entry_reason: string | null;
  opened_at: string | null;
}

export interface PositionsResponse {
  held: number;
  limit: number;
  items: PositionItem[];
  is_paper: boolean;
}
