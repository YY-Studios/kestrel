"use client";

// 전략설정 화면 (클라이언트 컴포넌트 — 슬라이더 인터랙션·저장).
// GET /api/strategy-settings로 현재값+안전범위(spec)를 받아 슬라이더로 조절하고 POST로 저장.
// 슬라이더 min/max = 안전 범위(네이티브 range라 범위 밖 불가) + 서버도 범위 검증(이중 안전).
//
// 경계: 이번 슬라이스는 저장까지 — engine 반영은 다음 단계. 저장돼도 실매매엔 아직 영향 없음(배너 안내).
// UI_GUIDE 준수: 다크모드 / 초록=이익·빨강=손실 / 차트 없음 / 보라·인디고·glass 없음 / 각진 카드.

import { useEffect, useState } from "react";
import type {
  SettingSpec,
  StrategySettings,
  StrategySettingsResponse,
} from "../../types/strategy";

// 클라이언트에서 api는 절대경로(프론트 :3000과 다른 :8000). CORS는 api에서 localhost:3000 허용.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
  orange: "#F97316",
} as const;

const GROUP_LABEL: Record<string, string> = {
  entry: "진입 조건",
  exit: "청산 조건",
  capital: "자금",
};

function formatValue(v: number, s: SettingSpec): string {
  switch (s.format) {
    case "pct":
      return `${Math.round(v * 100)}%`;
    case "pct_plus":
      return `+${Math.round(v * 100)}%`;
    case "pct_minus":
      return `−${Math.round(v * 100)}%`;
    case "usd":
      return `$${v.toLocaleString("en-US")}`;
    case "count":
      return `${v}${s.unit}`;
    default:
      return `${v}`;
  }
}

// 손절선만 빨강(손실 방향), 나머지 초록. (UI_GUIDE: 초록=이익·빨강=손실)
function accentFor(s: SettingSpec): string {
  return s.format === "pct_minus" ? C.down : C.up;
}

type SaveState =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "ok" }
  | { kind: "error"; message: string };

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

export default function StrategySettingsPage() {
  const [spec, setSpec] = useState<SettingSpec[] | null>(null);
  const [values, setValues] = useState<StrategySettings>({});
  const [initial, setInitial] = useState<StrategySettings>({});
  const [persisted, setPersisted] = useState(true);
  const [load, setLoad] = useState<"loading" | "ok" | "error">("loading");
  const [save, setSave] = useState<SaveState>({ kind: "idle" });

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/strategy-settings`, { cache: "no-store" });
        if (!res.ok) throw new Error(String(res.status));
        const body = (await res.json()) as StrategySettingsResponse;
        if (!alive) return;
        setSpec(body.spec);
        setValues(body.settings);
        setInitial(body.settings);
        setPersisted(body.persisted !== false);
        setLoad("ok");
      } catch {
        if (alive) setLoad("error");
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  function setValue(key: string, raw: number) {
    setValues((v) => ({ ...v, [key]: raw }));
    setSave({ kind: "idle" });
  }

  function resetDefaults() {
    if (!spec) return;
    setValues(Object.fromEntries(spec.map((s) => [s.key, s.default])));
    setSave({ kind: "idle" });
  }

  async function onSave() {
    setSave({ kind: "saving" });
    try {
      const res = await fetch(`${API_BASE}/api/strategy-settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: values }),
      });
      if (!res.ok) {
        let detail = `저장 실패 (HTTP ${res.status})`;
        try {
          const body = (await res.json()) as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch {
          /* ignore */
        }
        setSave({ kind: "error", message: detail });
        return;
      }
      const body = (await res.json()) as StrategySettingsResponse;
      setValues(body.settings);
      setInitial(body.settings);
      setSave({ kind: "ok" });
    } catch {
      setSave({ kind: "error", message: "네트워크 오류 — api 서버를 확인하세요." });
    }
  }

  const title = (
    <div style={{ marginBottom: 4 }}>
      <h1 style={{ fontSize: 24, fontWeight: 600, color: C.text, margin: 0 }}>전략 설정</h1>
    </div>
  );

  if (load === "loading") {
    return (
      <Shell>
        {title}
        <div style={{ fontSize: 13, color: C.label, marginTop: 16 }}>불러오는 중…</div>
      </Shell>
    );
  }

  if (load === "error" || spec === null) {
    return (
      <Shell>
        {title}
        <div
          style={{
            background: C.card,
            border: `1px solid ${C.border}`,
            borderRadius: 6,
            padding: 16,
            marginTop: 16,
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

  const dirty = spec.some((s) => values[s.key] !== initial[s.key]);
  const groups: Array<[string, SettingSpec[]]> = ["entry", "exit", "capital"].map((g) => [
    g,
    spec.filter((s) => s.group === g),
  ]);

  return (
    <Shell>
      {title}
      <div style={{ fontSize: 12, color: C.label, marginBottom: 18 }}>
        시나리오 1 · 틀은 고정, 임계값만 조절 가능
      </div>

      {!persisted && (
        <div
          style={{
            fontSize: 12,
            color: C.warn,
            background: "rgba(250,204,21,0.08)",
            border: "1px solid rgba(250,204,21,0.3)",
            borderRadius: 6,
            padding: "10px 14px",
            marginBottom: 12,
          }}
        >
          설정 저장 테이블이 아직 없어 <b>기본값</b>을 표시하고 있습니다.{" "}
          <code>docs/supabase/strategy_settings.sql</code> 을 실행하면 저장이 활성화됩니다.
        </div>
      )}

      {groups.map(([group, specs]) =>
        specs.length === 0 ? null : (
          <div
            key={group}
            style={{
              background: C.card,
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              padding: 16,
              marginBottom: 12,
            }}
          >
            <div
              style={{
                fontSize: 11,
                color: C.label,
                textTransform: "uppercase",
                letterSpacing: 0.5,
                marginBottom: 16,
              }}
            >
              {GROUP_LABEL[group]}
            </div>
            {specs.map((s, i) => {
              const val = values[s.key];
              const accent = accentFor(s);
              return (
                <div key={s.key} style={{ marginBottom: i === specs.length - 1 ? 0 : 18 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      marginBottom: 8,
                    }}
                  >
                    <span style={{ fontSize: 13, color: C.text }}>{s.label}</span>
                    <span style={{ fontSize: 13, color: accent, fontFamily: "monospace" }}>
                      {formatValue(val, s)}
                    </span>
                  </div>
                  <input
                    type="range"
                    min={s.min}
                    max={s.max}
                    step={s.step}
                    value={val}
                    onChange={(e) => setValue(s.key, Number(e.target.value))}
                    aria-label={s.label}
                    style={{ width: "100%", accentColor: accent, cursor: "pointer" }}
                  />
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 10,
                      color: C.disabled,
                      marginTop: 4,
                    }}
                  >
                    <span>{s.min_label}</span>
                    <span>{s.max_label}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ),
      )}

      {/* 오해 방지: 저장돼도 아직 엔진 미반영 */}
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "flex-start",
          background: "rgba(249,115,22,0.08)",
          border: "1px solid rgba(249,115,22,0.3)",
          borderRadius: 6,
          padding: "11px 14px",
          marginBottom: 14,
        }}
      >
        <span style={{ color: C.orange, fontSize: 13 }}>ⓘ</span>
        <span style={{ fontSize: 12, color: C.body, lineHeight: 1.5 }}>
          저장한 값은 <b style={{ color: C.text }}>아직 매매 엔진에 반영되지 않습니다</b> (다음
          단계). 지금은 설정을 저장만 하며, 진행 중인 매매·포지션에는 영향이 없습니다.
        </span>
      </div>

      {save.kind === "ok" && (
        <div style={{ fontSize: 12, color: C.up, marginBottom: 10 }}>✓ 저장되었습니다.</div>
      )}
      {save.kind === "error" && (
        <div style={{ fontSize: 12, color: C.orange, marginBottom: 10 }}>✗ {save.message}</div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={onSave}
          disabled={save.kind === "saving" || !dirty}
          style={{
            flex: 1,
            fontSize: 13,
            color: C.page,
            background: dirty ? C.text : C.disabled,
            border: "none",
            padding: 10,
            borderRadius: 6,
            cursor: save.kind === "saving" || !dirty ? "default" : "pointer",
          }}
        >
          {save.kind === "saving" ? "저장 중…" : "변경 사항 저장"}
        </button>
        <button
          onClick={resetDefaults}
          style={{
            fontSize: 13,
            color: C.body,
            background: "transparent",
            border: `1px solid ${C.border}`,
            padding: "10px 16px",
            borderRadius: 6,
            cursor: "pointer",
          }}
        >
          기본값 복원
        </button>
      </div>
    </Shell>
  );
}
