// 매매내역 화면 (SSR 서버 컴포넌트).
// api GET /api/orders를 서버에서 호출해 개별 체결(매수 1·2·3차 / 매도 익절·손절)을 최신순으로.
// 실데이터만 — 매수엔 실현손익 없음("—"), 매도엔 realized_pnl(이익 초록/손실 빨강).
//
// UI_GUIDE 준수: 다크모드 / 미국식 등락색 / 차트 없음(수치·뱃지) / 보라·인디고·glass 없음 /
// 각진 카드 / 청산유형 뱃지(익절 초록·손절 빨강·매수 중립).

import type { OrderItem, OrdersResponse } from "../../types/orders";

// --- 정식 팔레트 (docs/UI_GUIDE.md) ---
const C = {
  page: "#0E0F12",
  card: "#16181D",
  border: "#262A33",
  text: "#E8EAED",
  body: "#B0B4BC",
  label: "#787B86",
  disabled: "#4A4E57",
  up: "#22C55E",
  down: "#EF4444",
  warn: "#FACC15",
  blue: "#2962FF",   // 상태 성공 전용
  orange: "#F97316", // 상태 에러 전용
} as const;

const GRID = "1.1fr 0.9fr 1.1fr 1fr 0.7fr"; // 종목·구분 / 시간 / 수량·체결가 / 손익 / 상태

async function getOrders(): Promise<OrdersResponse | null> {
  const base = process.env.API_BASE_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/orders`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as OrdersResponse;
  } catch {
    return null;
  }
}

// --- 포맷 헬퍼 ---

function fmtUsd(v: number | null): string {
  if (v === null) return "—";
  const abs = Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return v < 0 ? `-$${abs}` : `$${abs}`;
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${mm}/${dd} ${hh}:${mi}`;
}

// 구분(매수·N차 / 매도·익절·손절) 색: 익절 초록·손절 빨강·매수 중립.
function kindColor(o: OrderItem): string {
  if (o.liquidation === "tp") return C.up;
  if (o.liquidation === "sl") return C.down;
  return C.body; // 매수
}

function pnlColor(v: number | null): string {
  if (v === null || v === 0) return C.body;
  return v > 0 ? C.up : C.down;
}

// 상태: 접수/체결=파랑 점, 실패(rejected)=주황 점.
function statusMeta(status: string | null): { dot: string; text: string } {
  if (status === "rejected") return { dot: C.orange, text: "실패" };
  if (status === "submitted") return { dot: C.blue, text: "접수" };
  return { dot: C.label, text: status ?? "—" };
}

// --- 공용 ---

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main
      style={{
        maxWidth: 1152,
        margin: "0 auto",
        padding: "40px 24px",
        background: C.page,
        minHeight: "100vh",
      }}
    >
      {children}
    </main>
  );
}

function Card({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: 6,
        padding: 13,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// --- 행 ---

function OrderRow({ o }: { o: OrderItem }) {
  const st = statusMeta(o.status);
  const priceFmt = o.price != null ? `$${o.price.toFixed(2)}` : "—";
  const qtyFmt = o.quantity != null ? `${o.quantity}주` : "";

  return (
    <Card style={{ marginBottom: 7 }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: GRID,
          gap: 8,
          alignItems: "center",
        }}
      >
        {/* 종목 · 구분 */}
        <div>
          <span style={{ fontSize: 14, fontWeight: 500, color: C.text }}>{o.symbol}</span>
          <div style={{ fontSize: 11, color: kindColor(o), marginTop: 2 }}>
            {o.kind_label}
            {o.detail_label && ` · ${o.detail_label}`}
          </div>
        </div>

        {/* 시간 */}
        <span style={{ fontSize: 12, color: C.label }}>{fmtDateTime(o.created_at)}</span>

        {/* 수량 · 체결가 */}
        <span style={{ fontSize: 13, color: C.body, textAlign: "right", fontFamily: "monospace" }}>
          {qtyFmt && <span style={{ color: C.label }}>{qtyFmt} </span>}
          {priceFmt}
        </span>

        {/* 실현손익 (매도만) */}
        <span
          style={{
            fontSize: 13,
            textAlign: "right",
            fontFamily: "monospace",
            color: o.side === "sell" ? pnlColor(o.realized_pnl) : C.disabled,
          }}
        >
          {o.side === "sell"
            ? o.realized_pnl != null
              ? `${o.realized_pnl > 0 ? "+" : ""}${fmtUsd(o.realized_pnl)}`
              : "—"
            : "—"}
        </span>

        {/* 상태 (+ 주문번호) */}
        <div style={{ textAlign: "right" }}>
          <span style={{ fontSize: 11, color: C.body, whiteSpace: "nowrap" }}>
            <span
              style={{
                display: "inline-block",
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: st.dot,
                marginRight: 5,
                verticalAlign: "middle",
              }}
            />
            {st.text}
          </span>
          {o.broker_order_id && (
            <div style={{ fontSize: 10, color: C.disabled, marginTop: 2 }}>
              #{o.broker_order_id}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

// --- 페이지 ---

export default async function OrdersPage() {
  const data = await getOrders();

  if (data === null) {
    return (
      <Shell>
        <h1 style={{ fontSize: 24, fontWeight: 600, color: C.text, margin: "0 0 16px" }}>
          매매 내역
        </h1>
        <Card style={{ padding: 16 }}>
          <span style={{ color: C.warn }}>● </span>
          <span style={{ fontSize: 14, color: C.body }}>
            API가 응답하지 않습니다. api 서버를 확인하세요 (<code>make api</code> 또는{" "}
            <code>make up</code>).
          </span>
        </Card>
      </Shell>
    );
  }

  return (
    <Shell>
      {/* 헤더 */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 20,
        }}
      >
        <h1 style={{ fontSize: 24, fontWeight: 600, color: C.text, margin: 0 }}>매매 내역</h1>
        <span style={{ fontSize: 12, color: C.label }}>최근 {data.count}건</span>
      </div>

      {data.items.length === 0 ? (
        <Card style={{ padding: 16 }}>
          <span style={{ fontSize: 13, color: C.label }}>매매 내역이 없습니다.</span>
        </Card>
      ) : (
        <>
          {/* 열 헤더 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: GRID,
              gap: 8,
              padding: "0 13px 8px",
              fontSize: 10,
              color: C.disabled,
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}
          >
            <span>종목 · 구분</span>
            <span>시간</span>
            <span style={{ textAlign: "right" }}>수량 · 체결가</span>
            <span style={{ textAlign: "right" }}>실현손익</span>
            <span style={{ textAlign: "right" }}>상태</span>
          </div>
          {data.items.map((o, i) => (
            <OrderRow key={`${o.broker_order_id ?? "x"}:${o.order_type}:${o.created_at}:${i}`} o={o} />
          ))}
        </>
      )}
    </Shell>
  );
}
