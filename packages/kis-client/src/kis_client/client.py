"""한국투자증권(KIS) Open API REST 클라이언트 — 스켈레톤.

실제 엔드포인트 연동은 아직 비어 있습니다. 토큰 발급 / 시세 / 주문을
한 메서드씩 채워 넣으세요. 모의투자(paper)와 실전(base_url)만 분기해 둡니다.

KIS 문서: https://apiportal.koreainvestment.com/
- 접근토큰: POST /oauth2/tokenP
- 현재가:   GET  /uapi/domestic-stock/v1/quotations/inquire-price
- 주문:     POST /uapi/domestic-stock/v1/trading/order-cash
"""

from __future__ import annotations

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

    def __init__(self, config: KisConfig) -> None:
        self.config = config
        self._http = httpx.Client(base_url=config.base_url, timeout=10.0)
        self._access_token: str | None = None

    # --- 인증 ---------------------------------------------------------------
    def issue_access_token(self) -> str:
        """OAuth 접근토큰 발급.

        TODO: POST /oauth2/tokenP 호출 후 access_token을 self._access_token에 저장.
        토큰은 24시간 유효하므로 매 호출마다 발급하지 말고 캐시하세요.
        """
        raise NotImplementedError("KIS 접근토큰 발급을 구현하세요 (/oauth2/tokenP)")

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
