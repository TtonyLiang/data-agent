from types import SimpleNamespace

import pytest

from app import security


class FakeRequest:
    def __init__(self, path="/api/agent/list", headers=None):
        self.url = SimpleNamespace(path=path)
        self.headers = headers or {}
        self.client = SimpleNamespace(host="127.0.0.1")


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


@pytest.mark.asyncio
async def test_middleware_ignores_legacy_admin_api_key(monkeypatch):
    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: SimpleNamespace(
            admin_api_key="legacy-key",
            debug=False,
            api_rate_limit_per_minute=10,
            chat_stream_max_concurrent=1,
        ),
    )

    async def call_next(_request):
        return "ok"

    result = await security.auth_and_rate_limit_middleware(
        FakeRequest(path="/api/auth/logout"), call_next
    )

    assert result == "ok"


def test_rate_limit_exempt_paths_do_not_include_self_registration():
    assert "/api/auth/login" in security.PUBLIC_PATHS
    assert "/api/auth/register" not in security.PUBLIC_PATHS
