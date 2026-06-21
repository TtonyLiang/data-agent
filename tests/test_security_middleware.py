from types import SimpleNamespace

import pytest

from app import security


class FakeRequest:
    def __init__(self, path="/api/agent/list", headers=None):
        self.url = SimpleNamespace(path=path)
        self.headers = headers or {}
        self.client = SimpleNamespace(host="127.0.0.1")


def test_validate_admin_authorization_allows_debug_without_key(monkeypatch):
    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: SimpleNamespace(admin_api_key="", debug=True),
    )

    assert security.validate_admin_authorization(FakeRequest()) is None


def test_validate_admin_authorization_requires_key_in_production(monkeypatch):
    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: SimpleNamespace(admin_api_key="", debug=False),
    )

    response = security.validate_admin_authorization(FakeRequest())

    assert response.status_code == 503


def test_validate_admin_authorization_checks_bearer_token(monkeypatch):
    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: SimpleNamespace(admin_api_key="expected", debug=False),
    )

    assert (
        security.validate_admin_authorization(
            FakeRequest(headers={"authorization": "Bearer expected"})
        )
        is None
    )
    assert security.validate_admin_authorization(FakeRequest()).status_code == 401
    assert (
        security.validate_admin_authorization(
            FakeRequest(headers={"authorization": "Bearer wrong"})
        ).status_code
        == 401
    )


@pytest.mark.asyncio
async def test_auth_middleware_skips_health(monkeypatch):
    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: SimpleNamespace(
            admin_api_key="expected",
            debug=False,
            api_rate_limit_per_minute=1,
            chat_stream_max_concurrent=1,
        ),
    )

    async def call_next(_request):
        return "ok"

    result = await security.auth_and_rate_limit_middleware(FakeRequest(path="/health"), call_next)

    assert result == "ok"
