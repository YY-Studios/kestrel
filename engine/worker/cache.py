"""일봉 캐시 — 엔진 프로세스 메모리에 TTL 기반으로 일봉을 캐싱해 KIS 호출을 줄인다.

일봉은 하루 단위 데이터라 매 폴링 주기(5초)마다 다시 받을 이유가 없다. TTL(기본 1시간) 안이면
캐시를 반환해 KIS 호출을 0으로 만든다. **현재가는 캐싱하지 않는다**(실시간 값이 진입·손절·익절
판단의 기준). 재시작하면 캐시는 비는 게 정상(파일·DB 아님).

시계(clock)는 time.monotonic 기본 — 시스템 시각 변경에 영향받지 않는다. 테스트는 가짜 시계 주입.
조회 실패는 예외를 그대로 올린다(캐시에 저장하지 않음) — 호출부가 기존처럼 종목을 건너뛴다.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger("kestrel.engine")

DEFAULT_TTL_SECONDS = 3600.0


class DailyPriceCache:
    """(exchange, symbol) → (fetched_at, daily) 를 TTL로 캐싱. broker는 get_overseas_daily_prices만 요구."""

    def __init__(
        self, ttl_seconds: float = DEFAULT_TTL_SECONDS, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._store: dict[tuple[str, str], tuple[float, Any]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, broker: Any, exchange: str, symbol: str) -> Any:
        """캐시에 있고 TTL 안이면 캐시 반환(KIS 호출 0). 없거나 만료면 KIS 조회 → 저장 → 반환.

        조회 실패 시 예외를 그대로 전파(캐시에 저장하지 않음) — 호출부가 종목을 건너뛴다.
        """
        key = (exchange, symbol)
        now = self._clock()
        cached = self._store.get(key)
        if cached is not None and (now - cached[0]) < self._ttl:
            self.hits += 1
            logger.debug("일봉 캐시 히트 %s/%s", exchange, symbol)
            return cached[1]

        # 미스/만료 — KIS 조회(실패 시 예외 전파, 저장 안 함)
        data = broker.get_overseas_daily_prices(exchange, symbol)
        self._store[key] = (now, data)
        self.misses += 1
        logger.debug("일봉 캐시 미스 %s/%s — KIS 조회", exchange, symbol)
        return data
