// 알림 화면 (SSR 서버 컴포넌트).
// api GET /api/alerts를 서버에서 호출해 선별된 사건(체결·진입 신호·추세 변화)을 시간순 피드로.
// 실데이터만 — 없으면 "알림이 없습니다".
//
// UI_GUIDE 준수: 다크모드 / 익절 초록·손절 빨강(손익), 체결 파랑·신호 노랑·실패 주황(상태) /
// 차트 없음 / 보라·인디고·glass 없음 / 아이콘은 인라인 SVG strokeWidth 1.5(둥근 박스로 안 감쌈).

import type { AlertItem, AlertsResponse, AlertSeverity } from "../../types/alerts";

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
  blue: "#2962FF",
  orange: "#F97316",
} as const;

// severity → 색 힌트(좌측 보더·아이콘).
const SEV_COLOR: Record<AlertSeverity, string> = {
  positive: C.up,
  negative: C.down,
  fill: C.blue,
  fail: C.orange,
  signal: C.warn,
  info: C.label,
};

async function getAlerts(): Promise<AlertsResponse | null> {
  const base = process.env.API_BASE_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/api/alerts`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as AlertsResponse;
  } catch {
    return null;
  }
}

function fmtTime(iso: string | null): string {
  if (!iso) return "";
  const m = iso.match(/\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/);
  return m ? `${m[1]} ${m[2]}` : "";
}

// severity별 아이콘 — 매수/체결·익절=위 화살표, 손절=아래 화살표, 실패=경고삼각, 신호/추세=점.
function AlertIcon({ severity }: { severity: AlertSeverity }) {
  const color = SEV_COLOR[severity];
  const common = {
    width: 15,
    height: 15,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: color,
    strokeWidth: 1.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  if (severity === "positive" || severity === "fill")
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 16V8M8 12l4-4 4 4" />
      </svg>
    );
  if (severity === "negative")
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8v8M8 12l4 4 4-4" />
      </svg>
    );
  if (severity === "fail")
    return (
      <svg {...common}>
        <path d="M12 3L2 20h20L12 3z" />
        <path d="M12 10v4M12 17h.01" />
      </svg>
    );
  // signal / info — 작은 점
  return (
    <svg {...common} fill={color}>
      <circle cx="12" cy="12" r="4" />
    </svg>
  );
}

function AlertRow({ a }: { a: AlertItem }) {
  const color = SEV_COLOR[a.severity];
  return (
    <div
      style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderLeftWidth: 3,
        borderLeftColor: color,
        borderRadius: "0 6px 6px 0",
        padding: "12px 14px",
        marginBottom: 7,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 3,
          gap: 8,
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13, color: C.text }}>
          <AlertIcon severity={a.severity} />
          <b style={{ fontWeight: 500 }}>{a.symbol}</b> {a.title}
        </span>
        <span style={{ fontSize: 11, color: C.label, whiteSpace: "nowrap" }}>
          {fmtTime(a.created_at)}
        </span>
      </div>
      {a.detail && (
        <div style={{ fontSize: 12, color: C.body, paddingLeft: 22 }}>{a.detail}</div>
      )}
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main
      style={{
        maxWidth: 720,
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

export default async function AlertsPage() {
  const data = await getAlerts();

  if (data === null) {
    return (
      <Shell>
        <h1 style={{ fontSize: 24, fontWeight: 600, color: C.text, margin: "0 0 16px" }}>알림</h1>
        <div
          style={{
            background: C.card,
            border: `1px solid ${C.border}`,
            borderRadius: 6,
            padding: 16,
          }}
        >
          <span style={{ color: C.warn }}>● </span>
          <span style={{ fontSize: 14, color: C.body }}>
            API가 응답하지 않습니다. api 서버를 확인하세요 (<code>make api</code> 또는{" "}
            <code>make up</code>).
          </span>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 20,
        }}
      >
        <h1 style={{ fontSize: 24, fontWeight: 600, color: C.text, margin: 0 }}>알림</h1>
        <span style={{ fontSize: 12, color: C.label }}>최근 {data.count}건</span>
      </div>

      {data.items.length === 0 ? (
        <div
          style={{
            background: C.card,
            border: `1px solid ${C.border}`,
            borderRadius: 6,
            padding: 16,
          }}
        >
          <span style={{ fontSize: 13, color: C.label }}>알림이 없습니다.</span>
        </div>
      ) : (
        data.items.map((a, i) => (
          <AlertRow key={`${a.kind}:${a.type}:${a.symbol}:${a.created_at}:${i}`} a={a} />
        ))
      )}
    </Shell>
  );
}
