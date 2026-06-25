#!/usr/bin/env python3
"""수동 확인용 — 실제 KIS 모의 도메인에 붙어 접근 토큰이 발급되는지 1회 확인.

이 스크립트는 **수동 확인용**이다. 자동 테스트(make test)에 넣지 마라 —
실제 네트워크를 타기 때문이다.

실행:
    make check-token
    # 또는: uv run --package kestrel-engine python scripts/check_token.py

동작:
    engine/.env 의 KIS 키를 읽어 broker-client.issue_access_token() 을 한 번 호출한다.
    기본 도메인은 모의(paper). KIS_IS_PAPER=false 일 때만 실전.

안전 규칙:
    키 값·토큰 전체는 절대 출력하지 않는다(성공 여부 + 토큰 앞 8자리만).
    (테스트용으로 KESTREL_ENV_FILE 환경변수로 .env 경로를 덮어쓸 수 있다.)
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import httpx

from broker_client import KisClient, KisConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = REPO_ROOT / "engine" / ".env"
TOKEN_CACHE = REPO_ROOT / ".kis_token_cache.json"  # .gitignore됨 — 토큰 재사용(1분 1회 제한 회피)


def _load_env(path: Path) -> dict[str, str]:
    """아주 단순한 .env 파서(KEY=VALUE). 인라인 주석(' #')·따옴표 제거."""
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
        print("   engine/.env.example 을 복사해 KIS 키를 채우세요:")
        print("     cp engine/.env.example engine/.env")
        return 1

    app_key, app_secret, account_no = get("KIS_APP_KEY"), get("KIS_APP_SECRET"), get("KIS_ACCOUNT_NO")
    # 기본값은 모의(paper). 'false' 일 때만 실전.
    is_paper = get("KIS_IS_PAPER").lower() != "false"

    if not app_key or not app_secret:
        print("⚠️  KIS_APP_KEY / KIS_APP_SECRET 가 비어 있습니다.")
        print(f"   {env_path} 에 모의투자 키를 채우세요. (값은 절대 커밋 금지)")
        return 1

    domain = "모의(paper)" if is_paper else "실전(real)"
    print(f"KIS 토큰 확보 시도 · 도메인: {domain}")

    client = KisClient(
        KisConfig(app_key=app_key, app_secret=app_secret, account_no=account_no, is_paper=is_paper),
        token_cache_path=str(TOKEN_CACHE),
    )
    cached_before = client._read_token_cache() is not None  # 유효 캐시 존재 여부(재사용/신규 구분용)
    try:
        token = client._ensure_token()  # 캐시 유효하면 재사용, 아니면 발급
    except httpx.HTTPStatusError as e:
        print(f"❌ 토큰 발급 실패 · HTTP {e.response.status_code}")
        try:
            body = e.response.json()
            code = body.get("error_code") or body.get("msg_cd") or body.get("rt_cd")
            msg = body.get("error_description") or body.get("msg1") or body.get("msg")
            print(f"   KIS 응답: code={code} · msg={msg}")
        except Exception:
            print(f"   KIS 응답(raw 일부): {e.response.text[:200]}")
        return 1
    except httpx.RequestError as e:
        print(f"❌ 네트워크 오류: {type(e).__name__}: {e}")
        return 1
    finally:
        client.close()

    head = (token or "")[:8]
    exp = client._token_expires_at
    exp_str = datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M:%S") if exp else "(만료정보 없음)"
    source = "캐시 재사용" if cached_before else "신규 발급"
    print(f"✅ 토큰 확보 성공({source}) · 도메인: {domain} · 토큰 앞 8자리: {head}… · 만료: {exp_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
