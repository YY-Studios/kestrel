#!/usr/bin/env python3
"""수동 확인용 — 실제 KIS 모의 도메인에서 해외주식 잔고를 1회 조회.

이 스크립트는 **수동 확인용**이다. 자동 테스트(make test)에 넣지 마라 — 실제 네트워크를 탄다.

실행:
    make check-balance
    # 또는: uv run --package kestrel-engine python scripts/check_balance.py

engine/.env 의 KIS 키로 연결해 예수금·평가자산·보유종목 요약을 출력한다.
키/토큰 전체는 절대 출력하지 않는다(잔고 금액·종목은 확인 위해 출력). KESTREL_ENV_FILE로 override 가능.

참고: 미국장 마감 시간대엔 현재가/평가가 직전 기준일 수 있으나 "데이터 수신"이면 연동은 정상이다.
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


def _fmt(v: float | None) -> str:
    return f"${v:,.2f}" if v is not None else "—(응답에 없음)"


def main() -> int:
    env_path = Path(os.environ.get("KESTREL_ENV_FILE") or DEFAULT_ENV)
    file_env = _load_env(env_path)

    def get(key: str) -> str:
        return (os.environ.get(key) or file_env.get(key) or "").strip()

    if not env_path.is_file():
        print(f"⚠️  .env 파일이 없습니다: {env_path}")
        print("   cp engine/.env.example engine/.env  후 KIS 키를 채우세요.")
        return 1

    app_key, app_secret, account_no = get("KIS_APP_KEY"), get("KIS_APP_SECRET"), get("KIS_ACCOUNT_NO")
    is_paper = get("KIS_IS_PAPER").lower() != "false"  # 기본 모의(paper)

    if not app_key or not app_secret or not account_no:
        print("⚠️  KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT_NO 가 비어 있습니다.")
        print(f"   {env_path} 를 채우세요. (값은 절대 커밋 금지)")
        return 1

    domain = "모의(paper)" if is_paper else "실전(real)"
    print(f"잔고 조회 시도 · 도메인: {domain}")

    client = KisClient(
        KisConfig(app_key=app_key, app_secret=app_secret, account_no=account_no, is_paper=is_paper),
        token_cache_path=str(TOKEN_CACHE),
    )
    try:
        bal = client.get_overseas_balance()
    except httpx.HTTPStatusError as e:
        print(f"❌ 잔고 조회 실패 · HTTP {e.response.status_code}")
        try:
            body = e.response.json()
            print(f"   KIS 응답: code={body.get('msg_cd')} · msg={body.get('msg1')}")
        except Exception:
            print(f"   KIS 응답(raw 일부): {e.response.text[:200]}")
        return 1
    except Exception as e:  # rt_cd≠0 등
        print(f"❌ 실패: {type(e).__name__}: {e}")
        return 1
    finally:
        client.close()

    print("✅ 연결 성공 · 잔고 요약:")
    print(f"   예수금       {_fmt(bal['deposit'])}")
    print(f"   평가금액     {_fmt(bal['eval_amount'])}")
    print(f"   총평가자산   {_fmt(bal['total_asset'])}")
    print(f"   총평가손익   {_fmt(bal['pnl_amount'])}")
    holdings = bal["holdings"]
    print(f"   보유종목     {len(holdings)}개")
    for h in holdings:
        qty = h["quantity"]
        print(f"     {h['symbol']:6} {qty}주 · 평단 {_fmt(h['avg_price'])} · 현재 {_fmt(h['current_price'])} · 평가손익 {_fmt(h['pnl_amount'])}")
    if bal["deposit"] is None and bal["total_asset"] is None and not holdings:
        print("   (요약이 비었음 — 응답 필드명이 다를 수 있음. broker_client.parse_overseas_balance 매핑 확인)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
