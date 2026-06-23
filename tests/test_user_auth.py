from types import SimpleNamespace

import pytest

from app import main
from app.api import agent as agent_api
from app.db import migrations
from app.models.user import PublicUser
from app.services import user_service
from app.services.user_service import (
    AuthError,
    PermissionDenied,
    UserService,
    hash_password,
    verify_password,
)


class FakeUserDB:
    def __init__(self):
        self.users: list[dict] = []
        self.permissions: set[tuple[int, int]] = set()
        self.next_id = 1

    async def execute_insert(self, sql: str, params: dict | None = None):
        params = params or {}
        if "INSERT INTO app_user" not in sql:
            raise AssertionError(sql)
        row = {
            "id": self.next_id,
            "username": params["username"],
            "password_hash": params["password_hash"],
            "display_name": params.get("display_name"),
            "role": params.get("role", "user"),
            "status": params.get("status", "active"),
            "must_change_password": params.get("must_change", 0),
            "created_at": None,
            "updated_at": None,
            "last_login_at": None,
        }
        self.users.append(row)
        self.next_id += 1
        return row["id"]

    async def execute_query(self, sql: str, params: dict | None = None):
        params = params or {}
        if "SELECT * FROM app_user WHERE username" in sql:
            return [user for user in self.users if user["username"] == params["username"]]
        if "SELECT * FROM app_user WHERE id" in sql:
            return [user for user in self.users if user["id"] == params["id"]]
        if "UPDATE app_user SET last_login_at" in sql:
            return []
        if "SELECT id, username" in sql and "FROM app_user" in sql:
            return list(self.users)
        if "UPDATE app_user SET status" in sql:
            for user in self.users:
                if user["id"] == params["id"]:
                    user["status"] = params["status"]
            return []
        if "UPDATE app_user SET password_hash" in sql:
            for user in self.users:
                if user["id"] == params["id"]:
                    user["password_hash"] = params["password_hash"]
                    user["must_change_password"] = params["must_change"]
            return []
        if "SELECT agent_id FROM user_agent_permission" in sql:
            return [
                {"agent_id": agent_id}
                for user_id, agent_id in sorted(self.permissions)
                if user_id == params["user_id"]
            ]
        if "SELECT 1 FROM user_agent_permission" in sql:
            key = (params["user_id"], params["agent_id"])
            return [{"ok": 1}] if key in self.permissions else []
        raise AssertionError(sql)

    async def execute_transaction(self, statements):
        for sql, params in statements:
            if sql.startswith("DELETE FROM user_agent_permission"):
                self.permissions = {
                    item for item in self.permissions if item[0] != params["user_id"]
                }
            elif sql.startswith("INSERT INTO user_agent_permission"):
                self.permissions.add((params["user_id"], params["agent_id"]))
            else:
                raise AssertionError(sql)


class FakeSeedDB:
    def __init__(self):
        self.admin_count = 0
        self.inserts: list[dict] = []

    async def execute_scalar(self, sql: str):
        assert "COUNT(*) FROM app_user WHERE role = 'admin'" in sql
        return self.admin_count

    async def execute_insert(self, sql: str, params: dict | None = None):
        assert "INSERT INTO app_user" in sql
        self.admin_count += 1
        self.inserts.append(params or {})
        return self.admin_count


class FakeAgentListDB:
    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []

    async def execute_query(self, sql: str, params: dict | None = None):
        self.calls.append((sql, params))
        return [
            {
                "id": 7,
                "name": "agent",
                "description": "demo",
                "llm_provider": "provider",
                "llm_model": "model",
                "api_key": "secret",
                "api_key_enabled": 1,
            }
        ]


def test_hash_password_uses_bcrypt_and_rejects_too_long_password():
    password_hash = hash_password("safe-password-123")

    assert password_hash != "safe-password-123"
    assert password_hash.startswith("$2")
    assert verify_password("safe-password-123", password_hash)
    assert not verify_password("wrong-password", password_hash)

    with pytest.raises(ValueError, match="密码过长"):
        hash_password("x" * 73)


@pytest.mark.asyncio
async def test_user_service_register_login_token_and_agent_permissions(monkeypatch):
    db = FakeUserDB()
    monkeypatch.setattr(user_service, "get_management_db", lambda: db)
    monkeypatch.setattr(
        user_service,
        "get_settings",
        lambda: SimpleNamespace(
            jwt_secret_key="test-jwt-secret-with-at-least-32-bytes",
            admin_api_key="",
            secret_encryption_key="",
            debug=True,
        ),
    )
    service = UserService()

    registered = await service.register_user("alice", "password123", "Alice")
    assert registered.username == "alice"
    assert not hasattr(registered, "password_hash")
    assert db.users[0]["password_hash"] != "password123"

    token, logged_in = await service.authenticate("alice", "password123")
    assert logged_in.id == registered.id
    assert (await service.get_user_by_token(token)).username == "alice"

    assert await service.can_access_agent(logged_in, 2) is False
    assert await service.set_user_agent_ids(logged_in.id, [3, 2, 2]) == [2, 3]
    assert await service.can_access_agent(logged_in, 2) is True
    assert await service.can_access_agent(
        PublicUser(id=99, username="admin", role="admin", status="active"),
        999,
    )

    await service.set_status(logged_in.id, "disabled")
    with pytest.raises(PermissionDenied):
        await service.authenticate("alice", "password123")

    with pytest.raises(AuthError):
        await service.authenticate("alice", "bad-password")


def test_user_service_rejects_short_jwt_secret_outside_debug(monkeypatch):
    monkeypatch.setattr(
        user_service,
        "get_settings",
        lambda: SimpleNamespace(
            jwt_secret_key="short-secret",
            admin_api_key="",
            secret_encryption_key="",
            debug=False,
        ),
    )
    service = UserService()

    with pytest.raises(AuthError, match="JWT 密钥"):
        service.create_access_token(
            PublicUser(id=1, username="admin", role="admin", status="active")
        )


@pytest.mark.asyncio
async def test_seed_default_admin_user_hashes_password_and_is_idempotent(monkeypatch):
    db = FakeSeedDB()
    initial_username = "seed-admin"
    initial_password = "test-admin-password-123"
    monkeypatch.setattr(migrations, "get_management_db", lambda: db)
    monkeypatch.setattr(
        migrations,
        "get_settings",
        lambda: SimpleNamespace(
            initial_admin_username=initial_username,
            initial_admin_password=initial_password,
            initial_admin_password_hash="",
        ),
    )

    await migrations.seed_default_admin_user()
    await migrations.seed_default_admin_user()

    assert len(db.inserts) == 1
    params = db.inserts[0]
    assert params["username"] == initial_username
    assert params["password_hash"] != initial_password
    assert verify_password(initial_password, params["password_hash"])


@pytest.mark.asyncio
async def test_seed_default_admin_user_skips_without_initial_secret(monkeypatch):
    db = FakeSeedDB()
    monkeypatch.setattr(migrations, "get_management_db", lambda: db)
    monkeypatch.setattr(
        migrations,
        "get_settings",
        lambda: SimpleNamespace(
            initial_admin_username="",
            initial_admin_password="",
            initial_admin_password_hash="",
        ),
    )

    await migrations.seed_default_admin_user()

    assert db.inserts == []


@pytest.mark.asyncio
async def test_seed_default_admin_user_accepts_configured_hash(monkeypatch):
    db = FakeSeedDB()
    initial_username = "seed-admin"
    configured_hash = hash_password("configured-secret")
    monkeypatch.setattr(migrations, "get_management_db", lambda: db)
    monkeypatch.setattr(
        migrations,
        "get_settings",
        lambda: SimpleNamespace(
            initial_admin_username=initial_username,
            initial_admin_password="",
            initial_admin_password_hash=configured_hash,
        ),
    )

    await migrations.seed_default_admin_user()

    assert len(db.inserts) == 1
    assert db.inserts[0]["username"] == initial_username
    assert db.inserts[0]["password_hash"] == configured_hash


@pytest.mark.asyncio
async def test_agent_list_filters_non_admin_by_user_permission(monkeypatch):
    db = FakeAgentListDB()
    monkeypatch.setattr(agent_api, "get_management_db", lambda: db)

    response = await agent_api.list_agents(
        current_user=PublicUser(id=8, username="bob", role="user", status="active")
    )

    sql, params = db.calls[0]
    assert "JOIN user_agent_permission" in sql
    assert params == {"user_id": 8}
    assert "api_key" not in response["agents"][0]


def test_session_filter_isolates_regular_users_and_keeps_admin_global_view():
    admin_filter, admin_params = main.scoped_session_filter(
        PublicUser(id=1, username="admin", role="admin", status="active"),
        agent_id=3,
    )
    user_filter, user_params = main.scoped_session_filter(
        PublicUser(id=9, username="user", role="user", status="active"),
        agent_id=3,
    )

    assert admin_filter == "agent_id = :aid"
    assert admin_params == {"aid": 3}
    assert user_filter == "agent_id = :aid AND user_id = :user_id"
    assert user_params == {"aid": 3, "user_id": 9}
