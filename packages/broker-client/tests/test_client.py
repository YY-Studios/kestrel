"""KIS 접근 토큰 발급 테스트.

실제 KIS 서버를 부르지 않는다 — httpx.MockTransport로 네트워크를 차단하고
가짜 응답을 주입한다. 테스트가 외부 네트워크를 타면 안 된다.
"""

from __future__ import annotations

import json

import httpx

from broker_client import KisClient, KisConfig
from broker_client.client import PAPER_BASE_URL, REAL_BASE_URL


def _client_with(config: KisConfig, handler) -> KisClient:
    """MockTransport를 주입한 KisClient를 만든다 (실제 네트워크 없음)."""
    return KisClient(config, transport=httpx.MockTransport(handler))


def test_issue_access_token_parses_token() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={"access_token": "fake-token-abc", "token_type": "Bearer", "expires_in": 86400},
        )

    client = _client_with(KisConfig(app_key="ak", app_secret="as", account_no="123"), handler)
    token = client.issue_access_token()

    assert token == "fake-token-abc"
    assert client._access_token == "fake-token-abc"  # 객체에 보관됨
    req = captured["request"]
    assert req.method == "POST"
    assert req.url.path == "/oauth2/tokenP"


def test_paper_uses_vts_domain() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})

    client = _client_with(
        KisConfig(app_key="ak", app_secret="as", account_no="123", is_paper=True), handler
    )
    client.issue_access_token()

    assert captured["request"].url.host == "openapivts.koreainvestment.com"
    assert str(captured["request"].url).startswith(PAPER_BASE_URL)


def test_real_uses_prod_domain() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})

    client = _client_with(
        KisConfig(app_key="ak", app_secret="as", account_no="123", is_paper=False), handler
    )
    client.issue_access_token()

    assert captured["request"].url.host == "openapi.koreainvestment.com"
    assert str(captured["request"].url).startswith(REAL_BASE_URL)


def test_request_carries_credentials() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})

    client = _client_with(
        KisConfig(app_key="MY_KEY", app_secret="MY_SECRET", account_no="123"), handler
    )
    client.issue_access_token()

    body = captured["body"]
    assert body["grant_type"] == "client_credentials"
    assert body["appkey"] == "MY_KEY"
    assert body["appsecret"] == "MY_SECRET"


def test_default_config_is_paper() -> None:
    # ADR-005: 기본값은 모의투자(paper).
    cfg = KisConfig(app_key="ak", app_secret="as", account_no="123")
    assert cfg.is_paper is True
    assert cfg.base_url == PAPER_BASE_URL


# --- 해외주식 시세 조회 (step 1b) -----------------------------------------

_PRICE_OK = {
    "rt_cd": "0",
    "msg_cd": "MCA00000",
    "msg1": "정상처리 되었습니다.",
    "output": {"rsym": "DNASAAPL", "last": "224.16", "base": "228.50", "tvol": "1234567"},
}


def _client_with_token(config: KisConfig, handler, token: str = "preset-token") -> KisClient:
    client = _client_with(config, handler)
    client._access_token = token  # 토큰은 이미 확보된 상태로 둔다(발급 호출 분리)
    return client


def test_get_overseas_price_parses_last() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_PRICE_OK)

    client = _client_with_token(KisConfig(app_key="ak", app_secret="as", account_no="123"), handler)
    result = client.get_overseas_price("NAS", "AAPL")

    assert result["symbol"] == "AAPL"
    assert result["exchange"] == "NAS"
    assert result["price"] == 224.16  # output.last 파싱(float)
    assert result["raw"]["last"] == "224.16"


def test_get_overseas_price_request_shape() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_PRICE_OK)

    client = _client_with_token(
        KisConfig(app_key="AK", app_secret="AS", account_no="123"), handler, token="tok-123"
    )
    client.get_overseas_price("NAS", "AAPL")

    req = captured["request"]
    assert req.method == "GET"
    assert req.url.path == "/uapi/overseas-price/v1/quotations/price"
    # 거래소·종목 코드가 쿼리에 실린다
    assert req.url.params["EXCD"] == "NAS"
    assert req.url.params["SYMB"] == "AAPL"
    # 토큰이 authorization 헤더에 실린다
    assert req.headers["authorization"] == "Bearer tok-123"
    assert req.headers["appkey"] == "AK"
    assert req.headers["appsecret"] == "AS"
    assert req.headers["tr_id"]  # tr_id 존재(해외 현재가)


def test_get_overseas_price_paper_domain() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_PRICE_OK)

    client = _client_with_token(
        KisConfig(app_key="ak", app_secret="as", account_no="123", is_paper=True), handler
    )
    client.get_overseas_price("NAS", "AAPL")
    assert captured["request"].url.host == "openapivts.koreainvestment.com"
    assert str(captured["request"].url).startswith(PAPER_BASE_URL)


def test_get_overseas_price_issues_token_if_missing() -> None:
    """토큰이 없으면 먼저 발급(/oauth2/tokenP)하고 시세를 조회한다."""
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "fresh-tok", "expires_in": 86400})
        return httpx.Response(200, json=_PRICE_OK)

    client = _client_with(KisConfig(app_key="ak", app_secret="as", account_no="123"), handler)
    assert client._access_token is None
    result = client.get_overseas_price("NAS", "AAPL")

    assert "/oauth2/tokenP" in seen_paths  # 토큰 발급이 선행됨
    assert "/uapi/overseas-price/v1/quotations/price" in seen_paths
    assert result["price"] == 224.16
    assert client._access_token == "fresh-tok"


def test_get_overseas_price_raises_on_kis_error() -> None:
    """KIS가 rt_cd != '0' (논리 오류)를 주면 메시지와 함께 예외."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "기간이 만료된 token 입니다."}
        )

    client = _client_with_token(KisConfig(app_key="ak", app_secret="as", account_no="123"), handler)
    try:
        client.get_overseas_price("NAS", "AAPL")
    except RuntimeError as e:
        assert "EGW00123" in str(e) or "만료" in str(e)
    else:
        raise AssertionError("rt_cd != '0' 이면 RuntimeError가 나야 한다")
