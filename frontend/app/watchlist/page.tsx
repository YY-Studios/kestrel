// 워치리스트 화면 (SSR 서버 컴포넌트).
// api(GET /api/watchlist)를 서버에서 호출해 표로 그린다. 서버→서버 호출이라 secret 키는
// 프론트에 노출되지 않는다(Supabase는 api가 service 키로 읽는다).
//
// UI_GUIDE 준수: 다크모드 고정 / 미국식 등락색(상승·충족=초록 #22C55E, 하락=빨강 #EF4444) /
// 차트 없이 수치·뱃지 / 보라·인디고 금지. 추세 미통과 종목은 흐리게(후보 아님), 신호 임박(2/3)은 강조.

import type { WatchlistItem, WatchlistResponse } from "../../types/watchlist";

// --- 정식 팔레트 (docs/UI_GUIDE.md) ---
const C = {
  page: "#0E0F12",
  card: "#16181D",
  border: "#262A33",
  text: "#E8EAED",
  body: "#B0B4BC",
  label: "#787B86",
  disabled: "#4A4E57",
  up: "#22C55E", // 상승·충족·목표
  down: "#EF4444", // 하락·미통과
  warn: "#FACC15", // 대기·경고
};

async function getWatchlist(): Promise<WatchlistResponse | null> {
  const base = process.env.API_BASE_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/watchlist`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as WatchlistResponse;
  } catch {
    return null;
  }
}

const GRID = "1.3fr 0.8fr 0.8fr 1fr 1fr 1.1fr";

function fmtTime(iso: string | null): string {
  if (!iso) return "";
  // 서버 렌더 결정성을 위해 ISO 문자열을 그대로 자른다(로케일/타임존 변동 회피). "2026-06-10T00:00:00Z" → "06-10 00:00"
  const m = iso.match(/\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/);
  return m ? `${m[1]} ${m[2]}` : "";
}

function TrendCell({ item }: { item: WatchlistItem }) {
  if (item.trend_ok === true)
    return <span style={{ fontSize: 12, color: C.up }}>✓ 통과</span>;
  if (item.trend_ok === false)
    return <span style={{ fontSize: 12, color: C.down }}>✗ 미통과</span>;
  return <span style={{ fontSize: 12, color: C.disabled }}>—</span>;
}

function RsiCell({ item }: { item: WatchlistItem }) {
  if (!item.has_signal || item.rsi === null)
    return <span style={{ fontSize: 13, color: C.disabled }}>—</span>;
  // RSI ≤ 35 = 과매도(반등 신호 충족) → 강조 초록, 그 외 본문색
  const oversold = item.rsi <= 35;
  return (
    <span style={{ fontSize: 13, color: oversold ? C.up : C.body }}>
      {Math.round(item.rsi)}
    </span>
  );
}

function FlagCell({ on, label }: { on: boolean | null; label: string }) {
  if (on)
    return <span style={{ fontSize: 12, color: C.up }}>{label} ✓</span>;
  return <span style={{ fontSize: 12, color: C.disabled }}>—</span>;
}

function SignalBadge({ item }: { item: WatchlistItem }) {
  const base = {
    fontSize: 11,
    padding: "3px 9px",
    borderRadius: 4,
    whiteSpace: "nowrap" as const,
  };
  if (!item.has_signal)
    return <span style={{ ...base, color: C.disabled }}>데이터 없음</span>;
  if (item.trend_ok === false)
    return <span style={{ ...base, color: C.disabled }}>후보 아님</span>;
  if (item.decision === "enter")
    return (
      <span style={{ ...base, color: C.up, background: "rgba(34,197,94,0.15)" }}>
        진입 신호 ✓
      </span>
    );
  const count = item.rebound_count ?? 0;
  const near = count >= 2; // 2개 이상 충족 = 매수 트리거 임박
  return (
    <span
      style={{
        ...base,
        color: near ? C.up : C.label,
        background: near ? "rgba(34,197,94,0.15)" : C.page,
      }}
    >
      {count}/3 {near ? "임박" : "대기"}
    </span>
  );
}

function Row({ item }: { item: WatchlistItem }) {
  const dim = item.trend_ok === false; // 추세 미통과 → 흐리게(후보 아님)
  return (
    <div
      style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: 6,
        padding: 12,
        marginBottom: 7,
        opacity: dim ? 0.55 : 1,
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: GRID,
          gap: 8,
          alignItems: "center",
        }}
      >
        <div>
          <span style={{ fontSize: 14, fontWeight: 500, color: C.text }}>
            {item.symbol}
          </span>
          <div style={{ fontSize: 11, color: C.label }}>
            {item.exchange}
            {item.updated_at ? ` · ${fmtTime(item.updated_at)}` : " · 데이터 없음"}
          </div>
        </div>
        <TrendCell item={item} />
        <RsiCell item={item} />
        <FlagCell on={item.bollinger_signal} label="하단" />
        <FlagCell on={item.macd_signal} label="반등" />
        <span style={{ textAlign: "right" }}>
          <SignalBadge item={item} />
        </span>
      </div>
    </div>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: 6,
        padding: 24,
        color: C.body,
        fontSize: 14,
        lineHeight: 1.7,
      }}
    >
      {children}
    </div>
  );
}

export default async function WatchlistPage() {
  const data = await getWatchlist();

  return (
    <main
      style={{
        maxWidth: 1152,
        margin: "0 auto",
        padding: "40px 24px",
        minHeight: "100vh",
        background: C.page,
      }}
    >
      <h1
        style={{
          fontSize: 24,
          fontWeight: 600,
          color: C.text,
          margin: "0 0 6px",
        }}
      >
        워치리스트
      </h1>

      {data === null ? (
        <>
          <p style={{ fontSize: 12, color: C.label, margin: "0 0 16px" }}>
            감시 종목 현황
          </p>
          <Panel>
            <span style={{ color: C.warn }}>● </span>
            API가 응답하지 않습니다. api 서버가 떠 있는지 확인하세요
            (<code>make api</code> 또는 <code>make up</code>).
          </Panel>
        </>
      ) : data.count === 0 ? (
        <>
          <p style={{ fontSize: 12, color: C.label, margin: "0 0 16px" }}>
            0종목 감시 중 · 추세 필터는 이 목록 안에서만 작동 (시장 전체 스캔 아님)
          </p>
          <Panel>
            감시 종목이 없습니다. Supabase <code>watchlist</code> 테이블에 감시할
            종목을 추가하세요.
          </Panel>
        </>
      ) : (
        <>
          <p style={{ fontSize: 12, color: C.label, margin: "0 0 16px" }}>
            {data.count}종목 감시 중 · 추세 필터는 이 목록 안에서만 작동 (시장 전체
            스캔 아님)
          </p>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: GRID,
              gap: 8,
              padding: "0 12px 8px",
              fontSize: 10,
              color: C.label,
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}
          >
            <span>종목</span>
            <span>추세</span>
            <span>RSI</span>
            <span>볼린저</span>
            <span>MACD</span>
            <span style={{ textAlign: "right" }}>신호</span>
          </div>

          {data.items.map((item) => (
            <Row key={`${item.exchange}:${item.symbol}`} item={item} />
          ))}

          <p style={{ fontSize: 11, color: C.disabled, marginTop: 12, lineHeight: 1.6 }}>
            추세 미통과(20일선 &lt; 60일선) 종목은 흐리게 표시되며 매매 후보에서
            제외됩니다. 반등 신호 3개(RSI≤35 · 볼린저 하단 · MACD 반등) 중 2개 이상이면
            매수 트리거입니다.
          </p>
        </>
      )}
    </main>
  );
}
