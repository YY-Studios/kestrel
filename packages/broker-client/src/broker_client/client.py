"""한국투자증권(KIS) Open API REST 클라이언트 — 스켈레톤.

실제 엔드포인트 연동은 아직 비어 있습니다. 토큰 발급 / 시세 / 주문을
한 메서드씩 채워 넣으세요. 모의투자(paper)와 실전(base_url)만 분기해 둡니다.

KIS 문서: https://apiportal.koreainvestment.com/
- 접근토큰: POST /oauth2/tokenP
- 현재가:   GET  /uapi/domestic-stock/v1/quotations/inquire-price
- 주문:     POST /uapi/domestic-stock/v1/trading/order-cash
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

# KIS가 제공하는 base_url. 모의투자와 실전이 다릅니다.
PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"
REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"


@dataclass
class KisConfig:
    app_key: str
    app_secret: str
    account_no: str
    is_paper: bool = True

    @property
    def base_url(self) -> str:
        return PAPER_BASE_URL if self.is_paper else REAL_BASE_URL


class KisClient:
    """KIS REST 호출을 감싸는 얇은 래퍼.

    사용 예:
        client = KisClient(KisConfig(app_key=..., app_secret=..., account_no=...))
        token = client.issue_access_token()
        price = client.get_price("005930")  # 삼성전자
    """

    def __init__(
        self, config: KisConfig, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.config = config
        # transport는 테스트에서 httpx.MockTransport를 주입하기 위한 통로다(실서비스에선 None).
        self._http = httpx.Client(
            base_url=config.base_url, timeout=10.0, transport=transport
        )
        self._access_token: str | None = None
        self._token_expires_at: float | None = None  # epoch초. 캐싱은 다음 step.

    # --- 인증 ---------------------------------------------------------------
    def issue_access_token(self) -> str:
        """OAuth 접근토큰 발급 (POST /oauth2/tokenP).

        paper/real 도메인은 config.base_url이 결정한다(기본 paper — ADR-005).
        발급한 토큰과 만료 시각을 객체에 보관해 둔다. (24시간 재사용 캐싱은 다음 step)
        """
        resp = self._http.post(
            "/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": self.config.app_key,
                "appsecret": self.config.app_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        expires_in = data.get("expires_in")
        if expires_in is not None:
            self._token_expires_at = time.time() + int(expires_in)
        return self._access_token

    # --- 시세 ---------------------------------------------------------------
    def get_price(self, symbol: str) -> dict:
        """현재가 조회.

        TODO: GET /uapi/domestic-stock/v1/quotations/inquire-price 구현.
        헤더에 appkey/appsecret/authorization(Bearer)/tr_id가 필요합니다.
        """
        raise NotImplementedError("KIS 현재가 조회를 구현하세요")

    # --- 주문 ---------------------------------------------------------------
    def place_order(self, symbol: str, quantity: int, side: str) -> dict:
        """주문 전송 (side: 'buy' | 'sell').

        TODO: POST /uapi/domestic-stock/v1/trading/order-cash 구현.
        모의/실전, 매수/매도에 따라 tr_id가 달라집니다.
        """
        raise NotImplementedError("KIS 주문 전송을 구현하세요")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "KisClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
