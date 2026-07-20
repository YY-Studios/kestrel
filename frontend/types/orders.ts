// 매매내역 응답 타입 — api(FastAPI) GET /api/orders 계약.
// realized_pnl은 매도(side=sell)에만 있다 — 매수는 null(가짜 손익 금지).

export interface OrderItem {
  symbol: string;
  exchange: string;
  side: string;                  // "buy" | "sell"
  order_type: string;            // buy_1/buy_2/buy_3 · sell_tp/sell_sl
  kind_label: string;            // "매수" | "매도"
  detail_label: string;          // "1차"/"2차"/"3차" · "익절"/"손절"
  liquidation: "tp" | "sl" | null; // 매도 청산 유형(뱃지 색)
  quantity: number | null;
  price: number | null;
  broker_order_id: string | null;
  status: string | null;
  realized_pnl: number | null;   // 매도만 · 매수는 null
  reason: string | null;
  created_at: string | null;
}

export interface OrdersResponse {
  count: number;
  items: OrderItem[];
}
