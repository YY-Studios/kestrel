// 포지션 화면 (SSR 서버 컴포넌트).
// api GET /api/positions를 서버에서 호출해 보유 종목의 분할단계·손익·청산거리를 그린다.
// 실데이터만 — 현재가 조회 실패 시 손익/거리는 "—", 화면은 평단·수량 등 DB값으로 안 깨진다.
//
// UI_GUIDE 준수: 다크모드 / 미국식 등락색(초록=#22C55E, 빨강=#EF4444) / 차트 없음(막대는 위치 마커) /
// 보라·인디고·glass morphism 없음 / 각진 카드 / paper 표기 / 표시 전용(주문은 engine 자동).

import type { PositionItem, PositionsResponse } from "../../types/positions";

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
} as const;

const TRANCHE_PCT = [40, 30, 30]; // 1·2·3차 비중 (PRD)
const STOP_NEAR_PCT = 2; // 손절까지 2% 이내면 경고(노랑)

async function getPositions(): Promise<PositionsResponse | null> {
  const base = process.env.API_BASE_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/positions`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as PositionsResponse;
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

function pnlColor(v: number | null): string {
  if (v === null || v === 0) return C.body;
  return v > 0 ? C.up : C.down; // 미국식: 이익 초록 · 손실 빨강
}

function signedPct(v: number | null): string {
  if (v === null) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

// --- 공용 ---

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
        padding: 16,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// --- 분할매수 단계 (1/3·2/3·3/3) ---

function TrancheStages({ stage }: { stage: number | null }) {
  const filled = stage ?? 0;
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 11, color: C.label, marginBottom: 6 }}>분할매수 단계</div>
      <div style={{ display: "flex", gap: 6 }}>
        {TRANCHE_PCT.map((pct, i) => {
          const done = i < filled;
          return (
            <div
              key={i}
              style={{
                flex: 1,
                textAlign: "center",
                padding: "7px 0",
                borderRadius: 4,
                fontSize: 11,
                background: done ? "rgba(34,197,94,0.13)" : C.page,
                color: done ? C.up : C.disabled,
              }}
            >
              {i + 1}차 {pct}% {done ? "✓" : "대기"}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --- 손절─현재─목표 막대 (현재가 위치 마커) ---

function StopTargetBar({ pos }: { pos: PositionItem }) {
  const { stop_price: stop, target_price: target, current_price: cur } = pos;
  const near =
    pos.stop_distance_pct != null && Math.abs(pos.stop_distance_pct) <= STOP_NEAR_PCT;

  // 마커 위치: 손절(0%)—목표(100%) 사이에서 현재가 위치. 데이터 부족/역전 시 마커 생략.
  let markerPct: number | null = null;
  if (stop != null && target != null && cur != null && target > stop) {
    markerPct = Math.min(100, Math.max(0, ((cur - stop) / (target - stop)) * 100));
  }

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 11,
          marginBottom: 6,
        }}
      >
        <span style={{ color: C.down }}>
          손절 {stop != null ? `$${stop.toFixed(2)}` : "—"}
        </span>
        <span style={{ color: C.label }}>
          현재 {cur != null ? `$${cur.toFixed(2)}` : "—"}
        </span>
        <span style={{ color: C.up }}>
          목표 {target != null ? `$${target.toFixed(2)}` : "—"}
        </span>
      </div>
      <div
        style={{
          height: 8,
          background: C.page,
          borderRadius: 4,
          position: "relative",
          overflow: "hidden",
          border: `1px solid ${C.border}`,
        }}
      >
        {markerPct != null && (
          <div
            style={{
              position: "absolute",
              left: `${markerPct}%`,
              top: -2,
              width: 3,
              height: 12,
              background: near ? C.warn : C.text,
              transform: "translateX(-1.5px)",
            }}
          />
        )}
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 11,
          marginTop: 6,
        }}
      >
        <span style={{ color: near ? C.warn : C.label }}>
          손절까지 {signedPct(pos.stop_distance_pct)}
        </span>
        <span style={{ color: C.label }}>목표까지 {signedPct(pos.target_distance_pct)}</span>
      </div>
    </div>
  );
}

// --- 포지션 카드 ---

function PositionCard({ pos }: { pos: PositionItem }) {
  const avgFmt = pos.avg_price != null ? `$${pos.avg_price.toFixed(2)}` : "—";
  const qtyFmt = pos.quantity != null ? `${pos.quantity}주` : "";
  const opened = fmtDate(pos.opened_at);

  return (
    <Card style={{ marginBottom: 12 }}>
      {/* 상단: 종목·평단·수량 / 손익 */}
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 17, fontWeight: 500, color: C.text }}>{pos.symbol}</div>
          <div style={{ fontSize: 12, color: C.label, marginTop: 2 }}>
            평단 {avgFmt}
            {qtyFmt && ` · ${qtyFmt}`}
            {opened && ` · 진입 ${opened}`}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          {pos.current_price != null ? (
            <>
              <div
                style={{
                  fontSize: 18,
                  fontWeight: 500,
                  fontFamily: "monospace",
                  color: pnlColor(pos.unrealized_pnl_pct),
                }}
              >
                {signedPct(pos.unrealized_pnl_pct)}
              </div>
              <div style={{ fontSize: 12, color: C.label, marginTop: 2 }}>
                현재 ${pos.current_price.toFixed(2)}
                {pos.unrealized_pnl != null && (
                  <span style={{ color: pnlColor(pos.unrealized_pnl), marginLeft: 4 }}>
                    {pos.unrealized_pnl > 0 ? "+" : ""}
                    {fmtUsd(pos.unrealized_pnl)}
                  </span>
                )}
              </div>
            </>
          ) : (
            <div style={{ fontSize: 12, color: C.disabled }}>현재가 준비 중</div>
          )}
        </div>
      </div>

      <TrancheStages stage={pos.tranche_stage} />
      <StopTargetBar pos={pos} />

      {pos.entry_reason && (
        <div style={{ fontSize: 11, color: C.label, marginTop: 12 }}>
          진입 근거 · {pos.entry_reason}
        </div>
      )}
    </Card>
  );
}

// --- 페이지 ---

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

export default async function PositionsPage() {
  const data = await getPositions();

  if (data === null) {
    return (
      <Shell>
        <h1 style={{ fontSize: 24, fontWeight: 600, color: C.text, margin: "0 0 16px" }}>
          포지션
        </h1>
        <Card>
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
          marginBottom: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h1 style={{ fontSize: 24, fontWeight: 600, color: C.text, margin: 0 }}>포지션</h1>
          <span
            style={{
              fontSize: 11,
              color: C.warn,
              border: `1px solid ${C.warn}`,
              padding: "2px 7px",
              borderRadius: 4,
            }}
          >
            {data.is_paper ? "모의투자 · PAPER" : "실전 · REAL"}
          </span>
        </div>
        <span style={{ fontSize: 12, color: C.label }}>
          보유 {data.held} / 한도 {data.limit}
        </span>
      </div>
      <div style={{ fontSize: 12, color: C.label, marginBottom: 20 }}>
        표시 전용 · 주문은 엔진이 자동 처리합니다.
      </div>

      {/* 목록 / 빈 상태 */}
      {data.items.length === 0 ? (
        <Card>
          <span style={{ fontSize: 13, color: C.label }}>보유 중인 포지션이 없습니다.</span>
        </Card>
      ) : (
        data.items.map((pos) => (
          <PositionCard key={`${pos.exchange}:${pos.symbol}`} pos={pos} />
        ))
      )}
    </Shell>
  );
}
