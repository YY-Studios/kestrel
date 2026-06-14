"""Kestrel 매매 엔진 워커 — 자동매매의 핵심.

별도 프로세스로 항상 돌면서 조건을 감시하고 주문을 낸다.
지금은 하트비트만 찍는 스켈레톤이다. 아래 루프 안의 TODO를 한 단계씩 채워라.

실행: `uv run python -m worker.main`  (engine/ 디렉터리에서)
종료: Ctrl+C (SIGINT) 또는 docker stop (SIGTERM) — 둘 다 깨끗하게 멈춘다.
"""

from __future__ import annotations

import logging
import signal
import time
from types import FrameType

from worker.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("kestrel.engine")

_running = True


def _handle_stop(signum: int, _frame: FrameType | None) -> None:
    global _running
    logger.info("종료 신호 수신(%s). 루프를 멈춥니다.", signum)
    _running = False


def main() -> None:
    settings = get_settings()
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    logger.info(
        "매매 엔진 시작 (paper=%s, interval=%ss)",
        settings.kis_is_paper,
        settings.poll_interval_seconds,
    )

    while _running:
        # TODO: 자동매매 루프 — 한 단계씩 구현하세요.
        #   1) Supabase에서 활성 전략 / 감시 종목 로드
        #   2) KisClient.get_price(symbol) 로 시세 조회
        #   3) 조건 평가 (예: 목표가 도달 여부)
        #   4) 충족 시 KisClient.place_order(...) 로 주문
        #   5) 주문 결과를 Supabase에 기록
        logger.info("heartbeat: 조건 감시 루프 (still empty)")
        time.sleep(settings.poll_interval_seconds)

    logger.info("매매 엔진 정상 종료")


if __name__ == "__main__":
    main()
