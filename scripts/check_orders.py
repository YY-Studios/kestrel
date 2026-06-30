#!/usr/bin/env python3
"""수동 확인용 — 실제 Supabase orders(체결 내역) 최근 N건 조회.

수동 확인용. 자동 테스트(make test)에 넣지 마라 — 실제 네트워크를 탄다.
실행: make check-orders   (또는 uv run --package kestrel-engine python scripts/check_orders.py [N])

engine/.env 의 SUPABASE_URL · SUPABASE_SERVICE_KEY 로 연결. 키는 출력하지 않는다.
아직 주문이 없으면 빈 목록이 정상이다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = REPO_ROOT / "engine" / ".env"
sys.path.insert(0, str(REPO_ROOT / "engine"))  # worker import (cwd 무관)

from worker.db import get_recent_orders, make_client  # noqa: E402


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

    print(f"orders 최근 {limit}건 조회")
    try:
        client = make_client(url, key)
        rows = get_recent_orders(client, limit)
    except Exception as e:
        print(f"❌ 실패: {type(e).__name__}: {e}")
        print("   (테이블 미생성이면 docs/supabase/orders.sql 을 SQL Editor에서 실행하세요.)")
        return 1

    if not rows:
        print("   (주문 내역 없음 — 아직 매매 전이면 빈 목록이 정상)")
        return 0
    for r in rows:
        ts = (r.get("created_at") or "")[:19]
        pnl = r.get("realized_pnl")
        pnl_s = f" 손익 {pnl}" if pnl is not None else ""
        print(
            f"   {ts} {r.get('exchange')}/{r.get('symbol')} · {r.get('side')} "
            f"{r.get('quantity')}주 @ {r.get('price')} · {r.get('order_type')} "
            f"[{r.get('status')}] ODNO={r.get('broker_order_id')}{pnl_s}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
