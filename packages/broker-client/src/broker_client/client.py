"""한국투자증권(KIS) Open API REST 클라이언트 — 스켈레톤.

실제 엔드포인트 연동은 아직 비어 있습니다. 토큰 발급 / 시세 / 주문을
한 메서드씩 채워 넣으세요. 모의투자(paper)와 실전(base_url)만 분기해 둡니다.

KIS 문서: https://apiportal.koreainvestment.com/
- 접근토큰: POST /oauth2/tokenP
- 현재가:   GET  /uapi/domestic-stock/v1/quotations/inquire-price
- 주문:     POST /uapi/domestic-stock/v1/trading/order-cash
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

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

# 토큰은 발급이 1분 1회로 제한(EGW00133)되므로 캐시해서 재사용한다. 만료 임박이면 미리 재발급.
TOKEN_EXPIRY_MARGIN = 60  # 초
# 초당 거래건수 초과(EGW00201)는 일시적 → 짧은 backoff 후 재시도.
RATE_LIMIT_MSG_CD = "EGW00201"


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
        self,
        config: KisConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        token_cache_path: str | Path | None = None,
        retry_backoff: float = 0.5,
        max_retries: int = 2,
    ) -> None:
        self.config = config
        # transport는 테스트에서 httpx.MockTransport를 주입하기 위한 통로다(실서비스에선 None).
        self._http = httpx.Client(
            base_url=config.base_url, timeout=10.0, transport=transport
        )
        self._access_token: str | None = None
        self._token_expires_at: float | None = None  # epoch초
        self._token_cache_path = token_cache_path  # 프로세스 간 토큰 재사용(.gitignore된 경로)
        self._retry_backoff = retry_backoff
        self._max_retries = max_retries

    # --- 요청 래퍼 (레이트리밋 재시도) --------------------------------------
    def _is_rate_limited(self, resp: httpx.Response) -> bool:
        """EGW00201(초당 거래건수 초과) 응답인지. 명시적 거부만 재시도한다."""
        try:
            return resp.json().get("msg_cd") == RATE_LIMIT_MSG_CD
        except Exception:
            return False

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """EGW00201(초당 초과)에만 backoff 후 재시도. 명시적 거부 응답이므로 주문도 안전(접수 안 됨).

        주의: 네트워크 예외(timeout 등 접수 불확실)는 재시도하지 않고 그대로 전파한다 — 중복 주문 방지.
        """
        for attempt in range(self._max_retries + 1):
            resp = self._http.request(method, path, **kwargs)
            if attempt < self._max_retries and self._is_rate_limited(resp):
                time.sleep(self._retry_backoff)
                continue
            return resp

    # --- 토큰 캐시 ----------------------------------------------------------
    def _read_token_cache(self) -> tuple[str, float] | None:
        """캐시에서 유효한(만료 여유 내, 같은 도메인) 토큰을 읽는다. 없으면 None."""
        if not self._token_cache_path:
            return None
        p = Path(self._token_cache_path)
        if not p.is_file():
            return None
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            return None
        token, exp = d.get("access_token"), d.get("expires_at")
        if not token or exp is None or d.get("base_url") != self.config.base_url:
            return None
        if (float(exp) - time.time()) <= TOKEN_EXPIRY_MARGIN:
            return None
        return token, float(exp)

    def _write_token_cache(self) -> None:
        if not self._token_cache_path or not self._access_token:
            return
        p = Path(self._token_cache_path)
        p.write_text(
            json.dumps(
                {
                    "access_token": self._access_token,
                    "expires_at": self._token_expires_at,
                    "base_url": self.config.base_url,
                }
            )
        )
        try:
            os.chmod(p, 0o600)  # 키와 동일한 보안 수준
        except OSError:
            pass

    def _token_valid(self) -> bool:
        if not self._access_token:
            return False
        if self._token_expires_at is None:
            return True  # 만료 정보 없이 주입된 토큰은 그대로 신뢰
        return (self._token_expires_at - time.time()) > TOKEN_EXPIRY_MARGIN

    # --- 인증 ---------------------------------------------------------------
    def issue_access_token(self) -> str:
        """OAuth 접근토큰 발급 (POST /oauth2/tokenP). 발급 후 캐시에 저장한다.

        paper/real 도메인은 config.base_url이 결정한다(기본 paper — ADR-005).
        ※ KIS는 발급을 1분 1회로 제한(EGW00133)하므로 보통 _ensure_token(캐시 경유)을 쓴다.
        """
        resp = self._request(
            "POST",
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
        self._write_token_cache()
        return self._access_token

    def _ensure_token(self) -> str:
        """유효한 토큰을 보장한다: 메모리 → 파일 캐시 → (없으면) 신규 발급 순.

        파일 캐시 덕에 매 실행/호출마다 재발급하지 않아 1분 1회 제한(EGW00133)을 피한다.
        """
        if self._token_valid():
            return self._access_token  # type: ignore[return-value]
        cached = self._read_token_cache()
        if cached is not None:
            self._access_token, self._token_expires_at = cached
            if self._token_valid():
                return self._access_token
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
        resp = self._request(
            "GET",
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
        resp = self._request(
            "POST",
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
