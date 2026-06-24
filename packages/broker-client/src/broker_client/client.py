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

# 해외주식 현재가(현재체결가) 조회 TR ID. 모의/실전 동일.
# 주의: 이 엔드포인트의 거래소 코드(EXCD)는 NAS/NYS/AMS 를 쓴다(주문용 NASD/NYSE/AMEX와 다름).
OVERSEAS_PRICE_TR_ID = "HHDFS00000300"
OVERSEAS_PRICE_PATH = "/uapi/overseas-price/v1/quotations/price"

# 해외주식 주문. 주문 거래소 코드(OVRS_EXCG_CD)는 NASD/NYSE/AMEX (시세의 NAS/NYS/AMS와 다름).
OVERSEAS_ORDER_PATH = "/uapi/overseas-stock/v1/trading/order"
# 모의(paper) 주문 TR ID. 실전(TTTT...)은 의도적으로 두지 않는다 — 실전은 별도 승인/ADR 후 활성화.
ORDER_TR_PAPER = {"buy": "VTTT1002U", "sell": "VTTT1001U"}
# 주문 거래소 코드 → 현재가 조회 거래소 코드 (±10% 검증용 시세 조회에 사용).
_ORDER_TO_PRICE_EXCD = {"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS"}
ORDER_PRICE_TOLERANCE = 0.10  # 지정가는 현재가 대비 ±10% 이내 (현지 거부 방지)


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
        price = client.get_overseas_price("NAS", "AAPL")  # 애플(나스닥)
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

    def _ensure_token(self) -> str:
        """확보된 토큰이 없으면 발급한다(프로세스 내 재사용). 24h 캐싱은 다음 step."""
        if not self._access_token:
            self.issue_access_token()
        assert self._access_token is not None
        return self._access_token

    # --- 시세 ---------------------------------------------------------------
    def get_overseas_price(self, exchange: str, symbol: str) -> dict:
        """해외주식 현재가 조회 (GET /uapi/overseas-price/v1/quotations/price).

        Args:
            exchange: 거래소 코드(EXCD). 현재가 조회는 NAS(나스닥)/NYS(뉴욕)/AMS(아멕스).
            symbol: 종목 코드(예: "AAPL").

        토큰은 내부에서 확보(발급/보관분 재사용)하고 authorization 헤더에 싣는다.
        반환: {"symbol", "exchange", "price"(float|None), "raw"(KIS output)}.
        미국장 마감 시간대(한국 낮)엔 직전 체결가가 올 수 있으나 "데이터 수신"은 정상이다.
        """
        token = self._ensure_token()
        resp = self._http.get(
            OVERSEAS_PRICE_PATH,
            headers={
                "authorization": f"Bearer {token}",
                "appkey": self.config.app_key,
                "appsecret": self.config.app_secret,
                "tr_id": OVERSEAS_PRICE_TR_ID,
            },
            params={"AUTH": "", "EXCD": exchange, "SYMB": symbol},
        )
        resp.raise_for_status()
        data = resp.json()
        rt_cd = data.get("rt_cd")
        if rt_cd is not None and rt_cd != "0":
            raise RuntimeError(
                f"KIS 시세 조회 실패: rt_cd={rt_cd} "
                f"msg_cd={data.get('msg_cd')} msg={data.get('msg1')}"
            )
        output = data.get("output") or {}
        last = output.get("last")
        price = float(last) if last not in (None, "") else None
        return {"symbol": symbol, "exchange": exchange, "price": price, "raw": output}

    def _split_account(self) -> tuple[str, str]:
        """계좌번호를 CANO(종합계좌) + ACNT_PRDT_CD(상품코드)로 분리."""
        acct = self.config.account_no.strip()
        if "-" in acct:
            cano, _, prdt = acct.partition("-")
            return cano.strip(), (prdt.strip() or "01")
        return acct[:8], (acct[8:] or "01")

    @staticmethod
    def _fmt_price(price: float) -> str:
        """KIS 지정가 문자열. 불필요한 0 제거 (146.78 → '146.78', 145.0 → '145')."""
        return f"{price:.4f}".rstrip("0").rstrip(".")

    # --- 주문 ---------------------------------------------------------------
    def place_overseas_order(
        self,
        exchange: str,
        symbol: str,
        quantity: int,
        side: str,
        price: float | None = None,
    ) -> dict:
        """해외주식 지정가 주문 (POST /uapi/overseas-stock/v1/trading/order).

        Args:
            exchange: 주문 거래소 코드(NASD/NYSE/AMEX).
            symbol: 종목 코드. quantity: 수량. side: 'buy' | 'sell'.
            price: 지정가. 미지정 시 현재가 기반. 모의는 **지정가만**(시장가 불가).

        안전장치:
            - **실전(real)은 차단한다.** is_paper=False면 RuntimeError(별도 승인/ADR 후 활성화).
            - 지정가는 현재가 대비 ±10% 이내만 허용(벗어나면 ValueError).
        """
        if side not in ("buy", "sell"):
            raise ValueError(f"side는 'buy' 또는 'sell' (받음: {side!r})")
        if not self.config.is_paper:
            raise RuntimeError(
                "실전(real) 주문은 비활성화 상태다. 모의(paper)에서만 동작한다 — "
                "실전 전환은 별도 승인/ADR(ROADMAP 실전 전환 트랙) 후 활성화한다."
            )

        # 현재가 확보(자동 지정가 + ±10% 검증). 주문 거래소→시세 거래소 매핑.
        price_excd = _ORDER_TO_PRICE_EXCD.get(exchange, exchange)
        current = self.get_overseas_price(price_excd, symbol)["price"]
        if price is None:
            if current is None:
                raise RuntimeError("현재가를 가져오지 못해 지정가를 정할 수 없다(미지정 시 현재가 필요).")
            price = current
        elif current is not None:
            lo, hi = current * (1 - ORDER_PRICE_TOLERANCE), current * (1 + ORDER_PRICE_TOLERANCE)
            if not (lo <= price <= hi):
                raise ValueError(
                    f"지정가 {price}가 현재가 {current} 대비 ±10% 범위를 벗어났다 "
                    f"(허용 {lo:.2f}~{hi:.2f}). 현지 거부 방지를 위해 차단한다."
                )

        token = self._ensure_token()
        cano, prdt = self._split_account()
        resp = self._http.post(
            OVERSEAS_ORDER_PATH,
            headers={
                "authorization": f"Bearer {token}",
                "appkey": self.config.app_key,
                "appsecret": self.config.app_secret,
                "tr_id": ORDER_TR_PAPER[side],
                "custtype": "P",
            },
            json={
                "CANO": cano,
                "ACNT_PRDT_CD": prdt,
                "OVRS_EXCG_CD": exchange,
                "PDNO": symbol,
                "ORD_QTY": str(quantity),
                "OVRS_ORD_UNPR": self._fmt_price(price),
                "ORD_DVSN": "00",  # 지정가
            },
        )
        resp.raise_for_status()
        data = resp.json()
        rt_cd = data.get("rt_cd")
        if rt_cd is not None and rt_cd != "0":
            raise RuntimeError(
                f"KIS 주문 실패: rt_cd={rt_cd} "
                f"msg_cd={data.get('msg_cd')} msg={data.get('msg1')}"
            )
        output = data.get("output") or {}
        return {
            "order_no": output.get("ODNO"),
            "symbol": symbol,
            "exchange": exchange,
            "side": side,
            "quantity": quantity,
            "price": price,
            "raw": output,
        }

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "KisClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
