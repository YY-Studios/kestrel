// 대시보드 화면 (SSR 서버 컴포넌트).
// api GET /api/dashboard를 서버에서 호출해 요약 카드를 그린다.
// 실데이터(예수금·평가자산·손익[KIS 잔고]·positions·watchlist 요약·전략 상태)를 표시.
// 잔고 조회 실패 또는 미구현(지수·환율·경제일정)은 "준비 중" 플레이스홀더 — 가짜 숫자 없음.
//
// UI_GUIDE 준수: 다크모드 / 미국식 등락색(초록=#22C55E, 빨강=#EF4444) / 차트 없음 /
// 보라·인디고·glass morphism 없음 / 각진 카드(rounded-md 수준).

import type { DashboardResponse, PositionItem } from "../../types/dashboard";

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

async function getDashboard(): Promise<DashboardResponse | null> {
  const base = process.env.API_BASE_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/dashboard`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as DashboardResponse;
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

function fmtPnl(amount: number | null, pct: number | null): string {
  if (amount === null) return "—";
  const signed = amount > 0 ? `+${fmtUsd(amount)}` : fmtUsd(amount);
  const pctStr =
    pct !== null ? ` (${pct > 0 ? "+" : ""}${pct.toFixed(2)}%)` : "";
  return `${signed}${pctStr}`;
}

// --- 공용 컴포넌트 ---

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
        padding: 14,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 10,
        color: C.label,
        textTransform: "uppercase",
        letterSpacing: 0.5,
        fontWeight: 500,
        marginBottom: 8,
      }}
    >
      {children}
    </div>
  );
}

function ComingSoon({ label }: { label: string }) {
  return (
    <Card>
      <SectionLabel>{label}</SectionLabel>
      <span style={{ fontSize: 12, color: C.disabled }}>준비 중</span>
    </Card>
  );
}

// --- 보유 포지션 ---

function TrancheTag({ stage }: { stage: number | null }) {
  if (stage === null) return null;
  return (
    <span
      style={{
        fontSize: 11,
        padding: "2px 8px",
        borderRadius: 4,
        background: C.page,
        color: C.label,
      }}
    >
      분할매수 {stage}/3
    </span>
  );
}

function PositionRow({ pos }: { pos: PositionItem }) {
  const avgFmt = pos.avg_price != null ? `$${pos.avg_price.toFixed(2)}` : "—";
  const qtyFmt = pos.quantity != null ? `${pos.quantity}주` : "";
  const targetDist =
    pos.target_price != null && pos.avg_price != null
      ? ((pos.target_price - pos.avg_price) / pos.avg_price) * 100
      : null;
  const stopDist =
    pos.stop_price != null && pos.avg_price != null
      ? ((pos.avg_price - pos.stop_price) / pos.avg_price) * 100
      : null;

  return (
    <Card style={{ marginBottom: 10 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 10,
        }}
      >
        <div>
          <span style={{ fontSize: 15, fontWeight: 500, color: C.text }}>
            {pos.symbol}
          </span>
          <span style={{ fontSize: 12, color: C.label, marginLeft: 8 }}>
            평단 {avgFmt} · {qtyFmt}
          </span>
        </div>
        <div style={{ textAlign: "right" }}>
          {pos.current_price != null ? (
            <div style={{ fontSize: 15, fontWeight: 500 }}>
              ${pos.current_price.toFixed(2)}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: C.disabled }}>
              현재가 준비 중
            </div>
          )}
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <TrancheTag stage={pos.tranche_stage} />
        {targetDist != null && (
          <span
            style={{
              fontSize: 11,
              padding: "2px 8px",
              borderRadius: 4,
              background: C.page,
              color: C.body,
            }}
          >
            목표 +{targetDist.toFixed(1)}%
          </span>
        )}
        {stopDist != null && (
          <span
            style={{
              fontSize: 11,
              padding: "2px 8px",
              borderRadius: 4,
              background: `rgba(239,68,68,0.1)`,
              color: C.down,
            }}
          >
            손절 −{stopDist.toFixed(1)}%
          </span>
        )}
      </div>
    </Card>
  );
}

// --- 페이지 ---

export default async function DashboardPage() {
  const data = await getDashboard();

  if (data === null) {
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
        <h1
          style={{ fontSize: 24, fontWeight: 600, color: C.text, margin: "0 0 16px" }}
        >
          대시보드
        </h1>
        <Card>
          <span style={{ color: C.warn }}>● </span>
          <span style={{ fontSize: 14, color: C.body }}>
            API가 응답하지 않습니다. api 서버를 확인하세요 (
            <code>make api</code> 또는 <code>make up</code>).
          </span>
        </Card>
      </main>
    );
  }

  const { positions, watchlist_summary, strategy, account } = data;

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
      {/* 헤더: 전략 상태 */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 24,
          paddingBottom: 16,
          borderBottom: `1px solid ${C.border}`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 18, fontWeight: 500, color: C.text }}>
            Kestrel
          </span>
          <span
            style={{
              fontSize: 11,
              color: C.warn,
              border: `1px solid ${C.warn}`,
              padding: "2px 7px",
              borderRadius: 4,
            }}
          >
            {strategy.is_paper ? "모의투자 · PAPER" : "실전"}
          </span>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 13,
            color: C.body,
          }}
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: C.up,
              display: "inline-block",
            }}
          />
          워치리스트 {strategy.watchlist_count}종목 감시 중
        </div>
      </div>

      {/* 지수·환율 — 준비 중 */}
      <Card style={{ marginBottom: 18, padding: "10px 14px" }}>
        <span style={{ fontSize: 12, color: C.disabled }}>
          지수·환율 (DOW · NASDAQ · S&P500 · 원/달러) — 준비 중
        </span>
      </Card>

      {/* 요약 카드 3개 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 10,
          marginBottom: 10,
        }}
      >
        {/* 총 평가자산 — KIS 잔고(실값) 또는 준비 중 */}
        <Card>
          <SectionLabel>총 평가자산</SectionLabel>
          {account.available ? (
            <>
              <div style={{ fontSize: 20, fontWeight: 500, color: C.text }}>
                {fmtUsd(account.total_asset)}
              </div>
              <div style={{ fontSize: 11, color: C.label, marginTop: 3 }}>
                예수금 + 평가 · {account.currency ?? "USD"}
              </div>
            </>
          ) : (
            <>
              <div style={{ fontSize: 12, color: C.disabled }}>준비 중</div>
              <div style={{ fontSize: 11, color: C.disabled, marginTop: 3 }}>
                잔고 조회 실패
              </div>
            </>
          )}
        </Card>

        {/* 예수금 — KIS 잔고(실값) 또는 준비 중 */}
        <Card>
          <SectionLabel>예수금</SectionLabel>
          {account.available ? (
            <>
              <div style={{ fontSize: 20, fontWeight: 500, color: C.text }}>
                {fmtUsd(account.deposit)}
              </div>
              <div style={{ fontSize: 11, color: C.label, marginTop: 3 }}>
                매수 가능
              </div>
            </>
          ) : (
            <>
              <div style={{ fontSize: 12, color: C.disabled }}>준비 중</div>
              <div style={{ fontSize: 11, color: C.disabled, marginTop: 3 }}>
                잔고 조회 실패
              </div>
            </>
          )}
        </Card>

        {/* 보유 / 한도 — 실데이터 */}
        <Card>
          <SectionLabel>보유 / 한도</SectionLabel>
          <div style={{ fontSize: 20, fontWeight: 500, color: C.text }}>
            {positions.held} / {positions.limit}
          </div>
          <div style={{ fontSize: 11, color: C.label, marginTop: 3 }}>
            {positions.limit - positions.held > 0
              ? `${positions.limit - positions.held}자리 여유`
              : "한도 가득"}
          </div>
        </Card>
      </div>

      {/* 손익 3개 — 준비 중 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 10,
          marginBottom: 18,
        }}
      >
        {/* 총 손익 — KIS 잔고(실값) 또는 준비 중 */}
        <Card>
          <SectionLabel>총 손익</SectionLabel>
          {account.available ? (
            <div
              style={{
                fontSize: 18,
                fontWeight: 500,
                color: pnlColor(account.pnl_amount),
              }}
            >
              {fmtPnl(account.pnl_amount, account.pnl_pct)}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: C.disabled }}>준비 중</div>
          )}
        </Card>
        {/* 주가/환차 분리·오늘 손익은 KIS 잔고에서 미제공 — 준비 중 */}
        <Card>
          <SectionLabel>└ 주가 / 환차</SectionLabel>
          <div style={{ fontSize: 12, color: C.disabled }}>준비 중</div>
        </Card>
        <Card>
          <SectionLabel>오늘 손익</SectionLabel>
          <div style={{ fontSize: 12, color: C.disabled }}>준비 중</div>
        </Card>
      </div>

      {/* 워치리스트 요약 — 실데이터 */}
      <Card style={{ marginBottom: 18 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div>
            <div style={{ fontSize: 13, color: C.text, marginBottom: 3 }}>
              시나리오 1 전략
            </div>
            <div style={{ fontSize: 12, color: C.label }}>
              워치리스트 {watchlist_summary.total}종목 감시 중 ·{" "}
              추세 통과 {watchlist_summary.trend_pass}종목
              {watchlist_summary.near_signal > 0 && (
                <span style={{ color: C.up, marginLeft: 6 }}>
                  · 신호 임박 {watchlist_summary.near_signal}종목
                </span>
              )}
              {watchlist_summary.enter_count > 0 && (
                <span style={{ color: C.up, marginLeft: 6, fontWeight: 500 }}>
                  · 진입 신호 {watchlist_summary.enter_count}종목
                </span>
              )}
            </div>
          </div>
          <a
            href="/watchlist"
            style={{ fontSize: 12, color: C.label, textDecoration: "none" }}
          >
            워치리스트 →
          </a>
        </div>
      </Card>

      {/* 보유 포지션 — 실데이터 */}
      <SectionLabel>보유 포지션</SectionLabel>
      {positions.items.length === 0 ? (
        <Card>
          <span style={{ fontSize: 13, color: C.label }}>
            보유 중인 포지션이 없습니다.
          </span>
        </Card>
      ) : (
        positions.items.map((pos) => (
          <PositionRow key={`${pos.exchange}:${pos.symbol}`} pos={pos} />
        ))
      )}

      {/* 경제 일정 — 준비 중 */}
      <div style={{ marginTop: 18 }}>
        <SectionLabel>다가오는 주요 일정</SectionLabel>
        <Card>
          <span style={{ fontSize: 12, color: C.disabled }}>준비 중</span>
        </Card>
      </div>
    </main>
  );
}
