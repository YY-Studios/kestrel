// 서버 컴포넌트(SSR). 페이지를 렌더하기 전에 서버에서 API 헬스체크를 호출합니다.
// 서버→서버 호출이므로 브라우저 CORS와 무관하며, 내부 주소(api:8000)를 씁니다.

async function getApiHealth(): Promise<{ status: string; kis_paper: boolean } | null> {
  const base = process.env.API_BASE_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${base}/health`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as { status: string; kis_paper: boolean };
  } catch {
    return null;
  }
}

export default async function Home() {
  const health = await getApiHealth();
  const online = health?.status === "ok";

  return (
    <main style={{ maxWidth: 640, margin: "0 auto", padding: "64px 24px" }}>
      <h1 style={{ fontSize: 32, marginBottom: 8 }}>🦅 Kestrel</h1>
      <p style={{ color: "#8b95a7", marginTop: 0 }}>자동매매 대시보드 — 스켈레톤</p>

      <section
        style={{
          marginTop: 32,
          padding: 20,
          borderRadius: 12,
          background: "#141925",
          border: "1px solid #232a3a",
        }}
      >
        <h2 style={{ fontSize: 16, margin: 0, color: "#8b95a7" }}>API 서버</h2>
        <p style={{ fontSize: 20, margin: "8px 0 0" }}>
          <span style={{ color: online ? "#3ddc84" : "#ff6b6b" }}>
            {online ? "● online" : "● offline"}
          </span>
          {online && (
            <span style={{ color: "#8b95a7", fontSize: 14, marginLeft: 12 }}>
              KIS {health?.kis_paper ? "모의투자" : "실전"} 모드
            </span>
          )}
        </p>
        {!online && (
          <p style={{ color: "#8b95a7", fontSize: 13, marginTop: 8 }}>
            API가 응답하지 않습니다. <code>docker compose up</code> 또는{" "}
            <code>uv run uvicorn app.main:app</code> 가 떠 있는지 확인하세요.
          </p>
        )}
      </section>
    </main>
  );
}
