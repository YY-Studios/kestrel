"""KIS 접근 토큰 발급 테스트.

실제 KIS 서버를 부르지 않는다 — httpx.MockTransport로 네트워크를 차단하고
가짜 응답을 주입한다. 테스트가 외부 네트워크를 타면 안 된다.
"""

from __future__ import annotations

import json
import time

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


# --- 해외주식 모의 주문 (step 1c) -----------------------------------------

_PRICE_PATH = "/uapi/overseas-price/v1/quotations/price"
_ORDER_PATH = "/uapi/overseas-stock/v1/trading/order"
_ORDER_OK = {"rt_cd": "0", "msg_cd": "APBK0013", "msg1": "주문 전송 완료", "output": {"ODNO": "0030123456"}}


def _route(price_last: str, order_resp: dict, captured: dict | None = None):
    """시세(±10% 검증용)·주문·토큰 경로를 라우팅하는 mock 핸들러."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == _PRICE_PATH:
            return httpx.Response(200, json={"rt_cd": "0", "output": {"last": price_last}})
        if path == _ORDER_PATH:
            if captured is not None:
                captured["request"] = request
                captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=order_resp)
        if path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 86400})
        return httpx.Response(404, json={})


    return handler


def test_place_order_buy_parses_order_no() -> None:
    cap: dict = {}
    client = _client_with_token(
        KisConfig(app_key="AK", app_secret="AS", account_no="50123456-01"),
        _route("145.00", _ORDER_OK, cap),
    )
    result = client.place_overseas_order("NASD", "AAPL", 1, "buy", price=146.78)

    assert result["order_no"] == "0030123456"
    req = cap["request"]
    assert req.method == "POST"
    assert req.url.path == _ORDER_PATH
    assert req.headers["tr_id"] == "VTTT1002U"  # 모의 매수
    assert req.headers["authorization"] == "Bearer preset-token"
    body = cap["body"]
    assert body["ORD_DVSN"] == "00"  # 지정가만
    assert body["ORD_SVR_DVSN_CD"] == "0"  # 주문서버구분코드(Default "0") — IGW00036 회피
    assert body["PDNO"] == "AAPL"
    assert body["OVRS_EXCG_CD"] == "NASD"  # 주문은 NASD
    assert body["ORD_QTY"] == "1"
    assert body["OVRS_ORD_UNPR"] == "146.78"
    # 계좌번호 분리 (CANO 8자리 + 상품코드)
    assert body["CANO"] == "50123456"
    assert body["ACNT_PRDT_CD"] == "01"


def test_place_order_sell_tr_id() -> None:
    cap: dict = {}
    client = _client_with_token(
        KisConfig(app_key="ak", app_secret="as", account_no="50123456-01"),
        _route("145.00", _ORDER_OK, cap),
    )
    client.place_overseas_order("NASD", "AAPL", 2, "sell", price=145.0)
    assert cap["request"].headers["tr_id"] == "VTTT1001U"  # 모의 매도
    assert cap["body"]["ORD_QTY"] == "2"
    assert cap["body"]["SLL_TYPE"] == "00"  # 매도 구분(일반 매도)


def test_place_order_buy_has_no_sll_type() -> None:
    cap: dict = {}
    client = _client_with_token(
        KisConfig(app_key="ak", app_secret="as", account_no="50123456-01"),
        _route("145.00", _ORDER_OK, cap),
    )
    client.place_overseas_order("NASD", "AAPL", 1, "buy", price=145.0)
    assert "SLL_TYPE" not in cap["body"]  # 매수엔 SLL_TYPE 없음


def test_place_order_paper_domain() -> None:
    cap: dict = {}
    client = _client_with_token(
        KisConfig(app_key="ak", app_secret="as", account_no="50123456-01", is_paper=True),
        _route("145.00", _ORDER_OK, cap),
    )
    client.place_overseas_order("NASD", "AAPL", 1, "buy", price=145.0)
    assert cap["request"].url.host == "openapivts.koreainvestment.com"
    assert str(cap["request"].url).startswith(PAPER_BASE_URL)


def test_place_order_auto_price_uses_current() -> None:
    cap: dict = {}
    client = _client_with_token(
        KisConfig(app_key="ak", app_secret="as", account_no="50123456-01"),
        _route("145.00", _ORDER_OK, cap),
    )
    client.place_overseas_order("NASD", "AAPL", 1, "buy")  # price 미지정 → 현재가 기반
    assert cap["body"]["OVRS_ORD_UNPR"] == "145"  # 현재가 145.00 → 지정가


def test_place_order_price_guard_blocks_out_of_range() -> None:
    # 현재가 100, 지정가 200 (+100%) → 주문 전 차단(주문 경로 미도달)
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _PRICE_PATH:
            return httpx.Response(200, json={"rt_cd": "0", "output": {"last": "100.00"}})
        raise AssertionError("가격 가드를 넘어 주문이 전송되면 안 된다")

    client = _client_with_token(KisConfig(app_key="ak", app_secret="as", account_no="50123456-01"), handler)
    try:
        client.place_overseas_order("NASD", "AAPL", 1, "buy", price=200.0)
    except ValueError as e:
        assert "10%" in str(e) or "범위" in str(e)
    else:
        raise AssertionError("±10% 벗어난 지정가는 ValueError로 차단돼야 한다")


def test_place_order_real_blocked() -> None:
    # 실전(is_paper=False)은 가드로 차단 — 네트워크/주문 미발생.
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("real 경로는 네트워크를 타면 안 된다")

    client = _client_with_token(
        KisConfig(app_key="ak", app_secret="as", account_no="50123456-01", is_paper=False), handler
    )
    try:
        client.place_overseas_order("NASD", "AAPL", 1, "buy", price=145.0)
    except RuntimeError as e:
        assert "real" in str(e).lower() or "실전" in str(e)
    else:
        raise AssertionError("실전 주문은 RuntimeError로 차단돼야 한다(별도 승인 전)")


def test_place_order_rt_cd_error() -> None:
    err = {"rt_cd": "1", "msg_cd": "APBK0919", "msg1": "장 시작 전입니다."}
    client = _client_with_token(
        KisConfig(app_key="ak", app_secret="as", account_no="50123456-01"),
        _route("145.00", err),
    )
    try:
        client.place_overseas_order("NASD", "AAPL", 1, "buy", price=145.0)
    except RuntimeError as e:
        assert "APBK0919" in str(e) or "장 시작" in str(e)
    else:
        raise AssertionError("rt_cd != '0' 이면 RuntimeError가 나야 한다")


# --- 토큰 캐싱 (EGW00133 회피, step 1d) ------------------------------------

def _fail_if_token_issued(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/oauth2/tokenP":
        raise AssertionError("유효한 캐시가 있으면 토큰을 재발급하면 안 된다")
    return httpx.Response(200, json={"access_token": "should-not-issue", "expires_in": 86400})


def _write_cache(path, token, expires_at, base_url=PAPER_BASE_URL) -> None:
    path.write_text(json.dumps({"access_token": token, "expires_at": expires_at, "base_url": base_url}))


def test_token_cache_reused_without_issuing(tmp_path) -> None:
    cache = tmp_path / "tok.json"
    _write_cache(cache, "cached-token", time.time() + 100000)
    client = KisClient(
        KisConfig(app_key="ak", app_secret="as", account_no="123"),
        transport=httpx.MockTransport(_fail_if_token_issued),
        token_cache_path=str(cache),
    )
    assert client._ensure_token() == "cached-token"  # 재발급 없이 캐시 재사용


def test_token_cache_expired_reissues(tmp_path) -> None:
    cache = tmp_path / "tok.json"
    _write_cache(cache, "old-token", time.time() - 10)  # 이미 만료

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "new-token", "expires_in": 86400})

    client = KisClient(
        KisConfig(app_key="ak", app_secret="as", account_no="123"),
        transport=httpx.MockTransport(handler),
        token_cache_path=str(cache),
    )
    assert client._ensure_token() == "new-token"
    # 캐시도 갱신됨
    assert json.loads(cache.read_text())["access_token"] == "new-token"


def test_token_cache_margin_reissues(tmp_path) -> None:
    # 만료 30초 전 → 여유(60초) 안이므로 재발급.
    cache = tmp_path / "tok.json"
    _write_cache(cache, "soon-expire", time.time() + 30)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "fresh", "expires_in": 86400})

    client = KisClient(
        KisConfig(app_key="ak", app_secret="as", account_no="123"),
        transport=httpx.MockTransport(handler),
        token_cache_path=str(cache),
    )
    assert client._ensure_token() == "fresh"


def test_issue_writes_cache(tmp_path) -> None:
    cache = tmp_path / "tok.json"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "issued-tok", "expires_in": 86400})

    client = KisClient(
        KisConfig(app_key="ak", app_secret="as", account_no="123"),
        transport=httpx.MockTransport(handler),
        token_cache_path=str(cache),
    )
    client.issue_access_token()
    assert cache.is_file()
    saved = json.loads(cache.read_text())
    assert saved["access_token"] == "issued-tok"
    assert saved["base_url"] == PAPER_BASE_URL


def test_token_cache_domain_mismatch_ignored(tmp_path) -> None:
    # 캐시가 real 도메인 토큰인데 config는 paper → 재사용 금지(재발급).
    cache = tmp_path / "tok.json"
    _write_cache(cache, "real-token", time.time() + 100000, base_url=REAL_BASE_URL)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "paper-token", "expires_in": 86400})

    client = KisClient(
        KisConfig(app_key="ak", app_secret="as", account_no="123", is_paper=True),
        transport=httpx.MockTransport(handler),
        token_cache_path=str(cache),
    )
    assert client._ensure_token() == "paper-token"


# --- 레이트리밋 재시도 (EGW00201, step 1d) --------------------------------

_RATE_LIMITED = {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."}


def test_rate_limit_retry_then_success() -> None:
    calls = {"price": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _PRICE_PATH:
            calls["price"] += 1
            if calls["price"] == 1:
                return httpx.Response(500, json=_RATE_LIMITED)  # 첫 호출 레이트리밋
            return httpx.Response(200, json={"rt_cd": "0", "output": {"last": "224.16"}})
        return httpx.Response(404, json={})

    client = KisClient(
        KisConfig(app_key="ak", app_secret="as", account_no="123"),
        transport=httpx.MockTransport(handler),
        retry_backoff=0.0,  # 테스트는 backoff 없이
    )
    client._access_token = "tok"
    result = client.get_overseas_price("NAS", "AAPL")
    assert result["price"] == 224.16
    assert calls["price"] == 2  # backoff 후 1회 재시도


def test_rate_limit_retries_exhausted_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _PRICE_PATH:
            return httpx.Response(500, json=_RATE_LIMITED)  # 계속 레이트리밋
        return httpx.Response(404, json={})

    client = KisClient(
        KisConfig(app_key="ak", app_secret="as", account_no="123"),
        transport=httpx.MockTransport(handler),
        retry_backoff=0.0,
    )
    client._access_token = "tok"
    try:
        client.get_overseas_price("NAS", "AAPL")
    except httpx.HTTPStatusError:
        pass  # 재시도 소진 후 500 → HTTPStatusError
    else:
        raise AssertionError("레이트리밋이 계속되면 최종적으로 예외가 나야 한다")


def test_order_not_retried_on_network_error() -> None:
    # 주문이 네트워크 오류(응답 불확실)면 재시도하지 않는다 — 중복 주문 방지.
    calls = {"order": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _PRICE_PATH:
            return httpx.Response(200, json={"rt_cd": "0", "output": {"last": "145.00"}})
        if request.url.path == _ORDER_PATH:
            calls["order"] += 1
            raise httpx.ConnectError("boom")  # 접수 불확실
        return httpx.Response(404, json={})

    client = KisClient(
        KisConfig(app_key="ak", app_secret="as", account_no="50123456-01"),
        transport=httpx.MockTransport(handler),
        retry_backoff=0.0,
    )
    client._access_token = "tok"
    try:
        client.place_overseas_order("NASD", "AAPL", 1, "buy", price=145.0)
    except httpx.RequestError:
        pass
    else:
        raise AssertionError("네트워크 오류는 그대로 전파돼야 한다")
    assert calls["order"] == 1  # 재시도 없이 1회만


# --- 해외주식 일봉(기간별 시세) 조회 (지표 데이터 토대) -----------------------

_DAILY_PATH = "/uapi/overseas-price/v1/quotations/dailyprice"
# KIS는 최신 일자가 먼저 온다(내림차순). 메서드는 과거→최신으로 정렬해 반환해야 한다.
_DAILY_OK = {
    "rt_cd": "0",
    "output2": [
        {"xymd": "20260624", "clos": "224.16"},
        {"xymd": "20260623", "clos": "222.00"},
        {"xymd": "20260620", "clos": "220.50"},
    ],
}


def test_get_daily_prices_parses_and_sorts_oldest_first() -> None:
    client = _client_with_token(
        KisConfig(app_key="ak", app_secret="as", account_no="123"),
        lambda req: httpx.Response(200, json=_DAILY_OK),
    )
    rows = client.get_overseas_daily_prices("NAS", "AAPL")
    # 과거 → 최신 순으로 (date, close) 튜플
    assert rows == [("20260620", 220.50), ("20260623", 222.00), ("20260624", 224.16)]


def test_get_daily_prices_request_shape() -> None:
    cap: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        cap["request"] = request
        return httpx.Response(200, json=_DAILY_OK)

    client = _client_with_token(
        KisConfig(app_key="AK", app_secret="AS", account_no="123"), handler, token="tok-xyz"
    )
    client.get_overseas_daily_prices("NAS", "AAPL")
    req = cap["request"]
    assert req.method == "GET"
    assert req.url.path == _DAILY_PATH
    assert req.url.params["EXCD"] == "NAS"
    assert req.url.params["SYMB"] == "AAPL"
    assert req.headers["tr_id"] == "HHDFS76240000"
    assert req.headers["authorization"] == "Bearer tok-xyz"


def test_get_daily_prices_paper_domain() -> None:
    cap: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        cap["request"] = request
        return httpx.Response(200, json=_DAILY_OK)

    client = _client_with_token(
        KisConfig(app_key="ak", app_secret="as", account_no="123", is_paper=True), handler
    )
    client.get_overseas_daily_prices("NAS", "AAPL")
    assert cap["request"].url.host == "openapivts.koreainvestment.com"
    assert str(cap["request"].url).startswith(PAPER_BASE_URL)


def test_get_daily_prices_rt_cd_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rt_cd": "1", "msg_cd": "EGW00121", "msg1": "조회 실패"})

    client = _client_with_token(KisConfig(app_key="ak", app_secret="as", account_no="123"), handler)
    try:
        client.get_overseas_daily_prices("NAS", "AAPL")
    except RuntimeError as e:
        assert "EGW00121" in str(e) or "조회 실패" in str(e)
    else:
        raise AssertionError("rt_cd != '0' 이면 RuntimeError가 나야 한다")


# --- 해외주식 잔고 조회 (get_overseas_balance) ---------------------------------

from broker_client.client import (  # noqa: E402
    OVERSEAS_BALANCE_PATH,
    OVERSEAS_BALANCE_TR_PAPER,
    OVERSEAS_BALANCE_TR_REAL,
    parse_overseas_balance,
)

# 실제 KIS present-balance 구조(check-balance로 확인): output1=보유(USD), output2=통화별 예수금.
_BALANCE_OK = {
    "rt_cd": "0",
    "msg_cd": "20310000",
    "output1": [
        {
            "pdno": "AAPL", "prdt_name": "APPLE INC", "buy_crcy_cd": "USD",
            "cblc_qty13": "8", "avg_unpr3": "228.50", "ovrs_now_pric1": "224.16",
            "frcr_evlu_amt2": "1793.28", "evlu_pfls_amt2": "-34.72", "evlu_pfls_rt1": "-1.90",
        },
        {
            "pdno": "NVDA", "prdt_name": "NVIDIA CORP", "buy_crcy_cd": "USD",
            "cblc_qty13": "15", "avg_unpr3": "138.20", "ovrs_now_pric1": "146.78",
            "frcr_evlu_amt2": "2201.70", "evlu_pfls_amt2": "128.70", "evlu_pfls_rt1": "6.20",
        },
    ],
    "output2": [
        {"crcy_cd": "CNY", "frcr_dncl_amt_2": "0.000000"},
        {"crcy_cd": "USD", "frcr_dncl_amt_2": "3120.00"},  # 미국 예수금(USD)
    ],
    "output3": {"tot_asst_amt": "390809135"},  # 원화 혼재 총액 — 파서는 쓰지 않음
}


def test_parse_overseas_balance_summary() -> None:
    b = parse_overseas_balance(_BALANCE_OK)
    assert b["deposit"] == 3120.00                    # output2 USD 행
    assert round(b["eval_amount"], 2) == 3994.98      # output1 합(1793.28+2201.70)
    assert round(b["total_asset"], 2) == 7114.98      # 예수금 + 평가
    assert round(b["pnl_amount"], 2) == 93.98         # 손익 합(-34.72+128.70)
    assert round(b["pnl_pct"], 2) == 2.41             # 93.98 / (3994.98-93.98) * 100
    assert b["currency"] == "USD"


def test_parse_overseas_balance_holdings() -> None:
    b = parse_overseas_balance(_BALANCE_OK)
    assert len(b["holdings"]) == 2
    aapl = b["holdings"][0]
    assert aapl["symbol"] == "AAPL" and aapl["name"] == "APPLE INC"
    assert aapl["quantity"] == 8.0 and aapl["avg_price"] == 228.50
    assert aapl["current_price"] == 224.16
    assert aapl["eval_amount"] == 1793.28 and aapl["pnl_amount"] == -34.72
    assert aapl["pnl_pct"] == -1.90


def test_parse_overseas_balance_missing_fields_are_none() -> None:
    b = parse_overseas_balance({"rt_cd": "0", "output1": [], "output2": []})
    assert b["deposit"] is None and b["total_asset"] is None
    assert b["eval_amount"] is None and b["holdings"] == []


def test_parse_overseas_balance_deposit_only_when_no_holdings() -> None:
    # 보유는 없고 예수금만 있으면 총자산=예수금
    data = {"rt_cd": "0", "output1": [], "output2": [{"crcy_cd": "USD", "frcr_dncl_amt_2": "500"}]}
    b = parse_overseas_balance(data)
    assert b["deposit"] == 500.0 and b["eval_amount"] is None
    assert b["total_asset"] == 500.0


def test_get_overseas_balance_request_shape() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_BALANCE_OK)

    client = _client_with_token(
        KisConfig(app_key="AK", app_secret="AS", account_no="12345678-01"), handler, token="tok-9"
    )
    client.get_overseas_balance()

    req = captured["request"]
    assert req.method == "GET"
    assert req.url.path == OVERSEAS_BALANCE_PATH
    assert req.headers["authorization"] == "Bearer tok-9"
    assert req.headers["appkey"] == "AK"
    assert req.headers["tr_id"] == OVERSEAS_BALANCE_TR_PAPER  # 모의 TR
    # 계좌번호가 CANO/ACNT_PRDT_CD로 분리돼 실린다
    assert req.url.params["CANO"] == "12345678"
    assert req.url.params["ACNT_PRDT_CD"] == "01"


def test_get_overseas_balance_paper_domain() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_BALANCE_OK)

    client = _client_with_token(
        KisConfig(app_key="ak", app_secret="as", account_no="123", is_paper=True), handler
    )
    client.get_overseas_balance()
    assert str(captured["request"].url).startswith(PAPER_BASE_URL)


def test_get_overseas_balance_uses_real_tr_when_not_paper() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_BALANCE_OK)

    client = _client_with_token(
        KisConfig(app_key="ak", app_secret="as", account_no="123", is_paper=False), handler
    )
    client.get_overseas_balance()
    # 조회는 실전 도메인/ TR을 쓴다(주문과 달리 잔고 조회는 real 차단 대상이 아님 — 읽기 전용)
    assert captured["request"].headers["tr_id"] == OVERSEAS_BALANCE_TR_REAL
    assert str(captured["request"].url).startswith(REAL_BASE_URL)


def test_get_overseas_balance_parses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_BALANCE_OK)

    client = _client_with_token(KisConfig(app_key="ak", app_secret="as", account_no="123"), handler)
    b = client.get_overseas_balance()
    assert b["deposit"] == 3120.00 and len(b["holdings"]) == 2


def test_get_overseas_balance_raises_on_kis_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "기간이 만료된 token"})

    client = _client_with_token(KisConfig(app_key="ak", app_secret="as", account_no="123"), handler)
    try:
        client.get_overseas_balance()
    except RuntimeError as e:
        assert "EGW00123" in str(e) or "조회 실패" in str(e)
    else:
        raise AssertionError("rt_cd != '0' 이면 RuntimeError가 나야 한다")
