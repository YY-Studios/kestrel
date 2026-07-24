// 알림 응답 타입 — api(FastAPI) GET /api/alerts 계약.
// signal_log(선별) + orders(전건)를 시간순 병합. severity가 색 힌트.

export type AlertSeverity =
  | "positive" // 익절(이익) — 초록
  | "negative" // 손절(손실) — 빨강
  | "fill" // 매수 체결 — 파랑(상태)
  | "fail" // 주문 실패 — 주황(상태)
  | "signal" // 진입 신호 — 노랑(신호)
  | "info"; // 추세 변화 — 중립

export interface AlertItem {
  kind: "order" | "signal";
  type: string; // buy_1 · sell_sl · enter · trend_pass · trend_break …
  symbol: string;
  title: string;
  detail: string;
  severity: AlertSeverity;
  realized_pnl: number | null;
  created_at: string | null;
}

export interface AlertsResponse {
  count: number;
  items: AlertItem[];
}
