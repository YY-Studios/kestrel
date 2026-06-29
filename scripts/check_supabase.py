#!/usr/bin/env python3
"""수동 확인용 — 실제 Supabase에 붙어 watchlist를 1회 조회.

수동 확인용. 자동 테스트(make test)에 넣지 마라 — 실제 네트워크를 탄다.

실행:
    make check-supabase
    # 또는: uv run --package kestrel-engine python scripts/check_supabase.py

engine/.env 의 SUPABASE_URL · SUPABASE_SERVICE_KEY 로 연결해 watchlist 행을 출력한다.
키는 절대 출력하지 않는다. KESTREL_ENV_FILE 로 .env 경로 override 가능.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = REPO_ROOT / "engine" / ".env"
# engine은 설치 패키지가 아니라 worker를 import하려면 경로를 추가한다(cwd 무관 동작).
sys.path.insert(0, str(REPO_ROOT / "engine"))

from worker.db import get_watchlist, make_client  # noqa: E402


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


def main() -> int:
    env_path = Path(os.environ.get("KESTREL_ENV_FILE") or DEFAULT_ENV)
    file_env = _load_env(env_path)

    def get(key: str) -> str:
        return (os.environ.get(key) or file_env.get(key) or "").strip()

    if not env_path.is_file():
        print(f"⚠️  .env 파일이 없습니다: {env_path}")
        print("   cp engine/.env.example engine/.env  후 SUPABASE_URL·SUPABASE_SERVICE_KEY를 채우세요.")
        return 1

    url, key = get("SUPABASE_URL"), get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("⚠️  SUPABASE_URL / SUPABASE_SERVICE_KEY 가 비어 있습니다.")
        print(f"   {env_path} 를 채우세요. (service 키는 서버 전용 — 절대 커밋 금지)")
        return 1

    print("Supabase 연결 시도 · watchlist 조회")
    try:
        client = make_client(url, key)
        rows = get_watchlist(client)
    except Exception as e:
        print(f"❌ 실패: {type(e).__name__}: {e}")
        print("   (테이블 미생성이면 README의 watchlist SQL을 Supabase SQL Editor에서 실행하세요.)")
        return 1

    print(f"✅ 연결 성공 · watchlist {len(rows)}개 종목:")
    for exchange, symbol in rows:
        print(f"   {exchange}/{symbol}")
    if not rows:
        print("   (비어 있음 — INSERT 후 다시 확인하거나, engine은 폴백 워치리스트로 동작)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
