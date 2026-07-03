"""api용 broker 팩토리 테스트 — 네트워크 없이 구성만 검증(실네트워크 0)."""

from __future__ import annotations

from broker_client import KisClient

from app import broker_client as bc


class _FakeSettings:
    kis_app_key = "AK"
    kis_app_secret = "AS"
    kis_account_no = "12345678-01"
    kis_is_paper = True


def test_get_broker_builds_paper_client(monkeypatch) -> None:
    monkeypatch.setattr(bc, "get_settings", lambda: _FakeSettings())
    client = bc.get_broker()
    try:
        assert isinstance(client, KisClient)
        assert client.config.is_paper is True          # 기본 모의(paper)
        assert client.config.account_no == "12345678-01"
    finally:
        client.close()
