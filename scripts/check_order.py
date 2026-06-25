#!/usr/bin/env python3
"""수동 확인용 — 실제 KIS 모의 계좌로 **딱 1회** 주문을 보내 본다 (매우 신중).

이 스크립트는 **수동 확인용**이다. 자동 테스트(make test)에 넣지 마라 — 실제 주문을 전송한다.
실행 전 사용자 확인(y/N)을 받고, 1회만 보낸다(반복·루프 없음).

실행:
    make check-order                                  # 기본: AAPL / NASD / 1주 / 매수 (paper)
    make check-order SYMBOL=TSLA QTY=1 SIDE=buy
    # 또는: uv run --package kestrel-engine python scripts/check_order.py AAPL NASD 1 buy

규칙:
    - 모의(paper) 전용. KIS_IS_PAPER=false면 스크립트가 거부한다(실전은 별도 승인 후).
    - 지정가만(가격 미지정 → 현재가 기반, ±10% 가드는 broker-client가 적용).
    - 키/토큰 전체는 출력하지 않는다.
    - 미국 정규장(한국 새벽) 외 시간엔 KIS가 주문을 거부할 수 있다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

from broker_client import KisClient, KisConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = REPO_ROOT / "engine" / ".env"
TOKEN_CACHE = REPO_ROOT / ".kis_token_cache.json"  # .gitignore됨 — 토큰 재사용(1분 1회 제한 회피)


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
    exchange = (argv[1] if len(argv) > 1 else "NASD").upper()
    qty = int(argv[2]) if len(argv) > 2 else 1
    side = (argv[3] if len(argv) > 3 else "buy").lower()

    if side not in ("buy", "sell"):
        print(f"⚠️  side는 buy 또는 sell (받음: {side})")
        return 1

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

    if not app_key or not app_secret or not account_no:
        print("⚠️  KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT_NO 중 비어있는 값이 있습니다.")
        print(f"   {env_path} 를 채우세요. (값은 절대 커밋 금지)")
        return 1

    # 실전 차단 — 이 스크립트는 모의 전용.
    if not is_paper:
        print("⛔ KIS_IS_PAPER=false (실전) 상태입니다. 이 확인 스크립트는 모의(paper) 전용입니다.")
        print("   실전 주문은 별도 승인/ADR(ROADMAP 실전 전환) 후에만 활성화합니다.")
        return 1

    side_ko = "매수" if side == "buy" else "매도"
    print("─" * 56)
    print(f"  모의투자(paper) 계좌로 주문을 보냅니다:")
    print(f"    {exchange} / {symbol} · {qty}주 · {side_ko} · 지정가(현재가 기반)")
    print("  ※ 미국 정규장(한국 새벽) 외 시간엔 거부될 수 있습니다.")
    print("─" * 56)
    answer = input("  진행할까요? (y/N) ").strip().lower()
    if answer != "y":
        print("취소했습니다. (주문 전송 안 함)")
        return 0

    client = KisClient(
        KisConfig(app_key=app_key, app_secret=app_secret, account_no=account_no, is_paper=is_paper),
        token_cache_path=str(TOKEN_CACHE),
    )
    try:
        result = client.place_overseas_order(exchange, symbol, qty, side)
    except ValueError as e:
        print(f"❌ 주문 차단(가격 가드): {e}")
        return 1
    except httpx.HTTPStatusError as e:
        print(f"❌ 주문 실패 · HTTP {e.response.status_code}")
        try:
            body = e.response.json()
            print(f"   KIS 응답: code={body.get('msg_cd') or body.get('error_code')} · msg={body.get('msg1') or body.get('error_description')}")
        except Exception:
            print(f"   KIS 응답(raw 일부): {e.response.text[:200]}")
        return 1
    except RuntimeError as e:
        print(f"❌ {e}")  # rt_cd != '0' (장 시작 전·미지원 종목 등) 또는 실전 차단
        return 1
    except httpx.RequestError as e:
        print(f"❌ 네트워크 오류: {type(e).__name__}: {e}")
        return 1
    finally:
        client.close()

    print(f"✅ 주문 전송 성공 · {exchange}/{symbol} {qty}주 {side_ko} · 주문번호(ODNO): {result['order_no']} · 지정가: {result['price']}")
    print("   (체결 여부는 모의 계좌/포지션에서 확인하세요. 지정가라 즉시 체결이 아닐 수 있음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
