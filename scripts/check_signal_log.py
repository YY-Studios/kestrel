#!/usr/bin/env python3
"""수동 확인용 — 실제 Supabase signal_log 최근 N건 조회.

수동 확인용. 자동 테스트(make test)에 넣지 마라 — 실제 네트워크를 탄다.
실행: make check-signal-log   (또는 uv run --package kestrel-engine python scripts/check_signal_log.py [N])

engine/.env 의 SUPABASE_URL · SUPABASE_SERVICE_KEY 로 연결. 키는 출력하지 않는다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = REPO_ROOT / "engine" / ".env"
sys.path.insert(0, str(REPO_ROOT / "engine"))  # worker import (cwd 무관)

from worker.db import SIGNAL_LOG_TABLE, make_client  # noqa: E402


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if " #" in val:
            val = val.split(" #", 1)[0].strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        env[key] = val
    return env


def main(argv: list[str]) -> int:
    limit = int(argv[0]) if argv else 10
    env_path = Path(os.environ.get("KESTREL_ENV_FILE") or DEFAULT_ENV)
    file_env = _load_env(env_path)

    def get(key: str) -> str:
        return (os.environ.get(key) or file_env.get(key) or "").strip()

    if not env_path.is_file():
        print(f"⚠️  .env 파일이 없습니다: {env_path}")
        return 1
    url, key = get("SUPABASE_URL"), get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("⚠️  SUPABASE_URL / SUPABASE_SERVICE_KEY 가 비어 있습니다.")
        return 1

    print(f"signal_log 최근 {limit}건 조회")
    try:
        client = make_client(url, key)
        resp = (
            client.table(SIGNAL_LOG_TABLE)
            .select("created_at,exchange,symbol,decision,trend_ok,pullback_pct,rebound_count,rsi")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = getattr(resp, "data", None) or []
    except Exception as e:
        print(f"❌ 실패: {type(e).__name__}: {e}")
        print("   (테이블 미생성이면 docs/supabase/signal_log.sql 을 SQL Editor에서 실행하세요.)")
        return 1

    if not rows:
        print("   (기록 없음 — make engine 을 잠깐 돌려 판단이 변하면 기록됩니다.)")
        return 0
    for r in rows:
        ts = (r.get("created_at") or "")[:19]
        print(
            f"   {ts} {r.get('exchange')}/{r.get('symbol')} · {r.get('decision')} "
            f"| 추세{'O' if r.get('trend_ok') else 'X'} 눌림{r.get('pullback_pct')} "
            f"반등{r.get('rebound_count')} RSI{r.get('rsi')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
