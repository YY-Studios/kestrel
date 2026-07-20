// 전략설정 응답 타입 — api(FastAPI) GET·POST /api/strategy-settings 계약.
// spec은 슬라이더 범위(안전 범위)의 단일 진실 — 프론트 슬라이더는 이 min/max 안에서만 움직인다.
// 저장 단위: %는 분수(0.08=8%), RSI·개수는 숫자 그대로.

export type SettingFormat = "num" | "pct" | "pct_plus" | "pct_minus" | "usd" | "count";
export type SettingGroup = "entry" | "exit" | "capital";

export interface SettingSpec {
  key: string;
  label: string;
  group: SettingGroup;
  min: number;
  max: number;
  step: number;
  type: "int" | "float";
  default: number;
  format: SettingFormat;
  unit: string;
  min_label: string;
  max_label: string;
}

export type StrategySettings = Record<string, number>;

export interface StrategySettingsResponse {
  settings: StrategySettings;
  spec: SettingSpec[];
  persisted?: boolean; // false면 DB 미연결/테이블 없음 — 기본값 표시 중(저장은 SQL 실행 후)
}
