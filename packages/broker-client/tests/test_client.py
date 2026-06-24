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
