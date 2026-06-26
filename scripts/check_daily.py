#!/usr/bin/env python3
"""수동 확인용 — 실제 KIS 모의 도메인에서 미국 종목 일봉(최근 종가)을 조회.

수동 확인용. 자동 테스트(make test)에 넣지 마라 — 실제 네트워크를 탄다.

실행:
    make check-daily                 # 기본 AAPL / NAS, 최근 5일 종가
    make check-daily SYMBOL=TSLA EXCD=NAS
    # 또는: uv run --package kestrel-engine python scripts/check_daily.py AAPL NAS

EXCD는 시세 계열 NAS/NYS/AMS. 키/토큰 전체는 출력하지 않는다(종가는 출력).
KESTREL_ENV_FILE로 .env 경로 override 가능.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

from broker_client import KisClient, KisConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = REPO_ROOT / "engine" / ".env"
TOKEN_CACHE = REPO_ROOT / ".kis_token_cache.json"  # .gitignore됨 — 토큰 재사용


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
    symbol = (argv[0] if len(argv) > 0 else "AAPL").upper()
    exchange = (argv[1] if len(argv) > 1 else "NAS").upper()

    env_path = Path(os.environ.get("KESTREL_ENV_FILE") or DEFAULT_ENV)
    file_env = _load_env(env_path)

    def get(key: str) -> str:
        return (os.environ.get(key) or file_env.get(key) or "").strip()

    if not env_path.is_file():
        print(f"⚠️  .env 파일이 없습니다: {env_path}")
        print("   cp engine/.env.example engine/.env  후 KIS 키를 채우세요.")
        return 1

    app_key, app_secret, account_no = get("KIS_APP_KEY"), get("KIS_APP_SECRET"), get("KIS_ACCOUNT_NO")
    is_paper = get("KIS_IS_PAPER").lower() != "false"

    if not app_key or not app_secret:
        print("⚠️  KIS_APP_KEY / KIS_APP_SECRET 가 비어 있습니다.")
        print(f"   {env_path} 에 모의투자 키를 채우세요. (값은 절대 커밋 금지)")
        return 1

    domain = "모의(paper)" if is_paper else "실전(real)"
    print(f"일봉 조회 시도 · {exchange}/{symbol} · 도메인: {domain}")

    client = KisClient(
        KisConfig(app_key=app_key, app_secret=app_secret, account_no=account_no, is_paper=is_paper),
        token_cache_path=str(TOKEN_CACHE),
    )
    try:
        rows = client.get_overseas_daily_prices(exchange, symbol)
    except httpx.HTTPStatusError as e:
        print(f"❌ 일봉 조회 실패 · HTTP {e.response.status_code}")
        try:
            body = e.response.json()
            print(f"   KIS 응답: code={body.get('msg_cd') or body.get('error_code')} · msg={body.get('msg1') or body.get('error_description')}")
        except Exception:
            print(f"   KIS 응답(raw 일부): {e.response.text[:200]}")
        return 1
    except RuntimeError as e:
        print(f"❌ {e}")
        return 1
    except httpx.RequestError as e:
        print(f"❌ 네트워크 오류: {type(e).__name__}: {e}")
        return 1
    finally:
        client.close()

    if not rows:
        print("✅ 응답 수신했으나 일자별 데이터가 비어 있음 (종목/거래소·기간 확인 필요)")
        return 0

    recent = rows[-5:]  # 과거→최신 정렬이므로 뒤 5개가 최근
    print(f"✅ 일봉 수신 성공 · {exchange}/{symbol} · 총 {len(rows)}일 · 최근 {len(recent)}일 종가:")
    for day, close in recent:
        print(f"   {day} · {close}")
    print("   (지표 계산은 다음 슬라이스 — 이번엔 데이터 수신만 확인)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
