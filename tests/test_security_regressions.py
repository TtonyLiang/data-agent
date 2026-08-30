import pytest
from fastapi import HTTPException

from app import main
from app.api import agent as agent_api
from app.api import datasource as datasource_api
from app.db.mysql import safe_param_keys
from app.models.user import PublicUser

ADMIN_USER = PublicUser(id=1, username="admin", role="admin", status="active")


def test_mysql_log_param_keys_redacts_sensitive_names():
    keys = safe_param_keys(
        {
            "username": "alice",
            "password": "plain",
            "password_hash": "hash",
            "api_key": "key",
            "agent_id": 1,
        }
    )

    assert "username" in keys
    assert "agent_id" in keys
    assert "password" not in keys
    assert "password_hash" not in keys
    assert "api_key" not in keys
    assert "***REDACTED***" in keys


class FakeDatasource:
    id = 7

    def model_dump(self, exclude=None):
        data = {
            "id": 7,
            "agent_id": 1,
            "name": "finance",
            "db_type": "mysql",
            "host": "127.0.0.1",
            "port": 3306,
            "username": "root",
            "password": "secret",
            "database_name": "business_db",
            "status": "active",
        }
        for key in exclude or set():
            data.pop(key, None)
        return data


class FakeDatasourceService:
    async def list_by_agent(self, agent_id: int):
        return [FakeDatasource()]

    async def belongs_to_agent(self, datasource_id: int, agent_id: int):
        return False


class FakeGraph:
    seen_state: dict | None = None

    async def ainvoke(self, state, config=None):
        self.seen_state = state
        if state.get("datasource_id") == 7:
            return {"final_answer": "ok", "sql_result": [], "execution_trace": {}}
        raise AssertionError("graph should not run for foreign datasource")


class FakeManagementDB:
    async def execute_query(self, sql: str, params: dict | None = None):
        return [
            {
                "id": 1,
                "name": "agent",
                "description": "demo",
                "llm_provider": "ollama",
                "llm_model": "qwen3",
                "api_key": "agent-secret",
                "api_key_enabled": 1,
            }
        ]


@pytest.mark.asyncio
async def test_datasource_list_does_not_return_password(monkeypatch):
    monkeypatch.setattr(
        datasource_api,
        "get_datasource_service",
        lambda: FakeDatasourceService(),
    )

    response = await datasource_api.list_datasources(agent_id=1, _=ADMIN_USER)

    assert "password" not in response["datasources"][0]
    assert response["datasources"][0]["username"] == "root"


@pytest.mark.asyncio
async def test_agent_list_does_not_return_api_key(monkeypatch):
    monkeypatch.setattr(agent_api, "get_management_db", lambda: FakeManagementDB())

    response = await agent_api.list_agents(current_user=ADMIN_USER)

    assert "api_key" not in response["agents"][0]
    assert response["agents"][0]["api_key_enabled"] == 1


@pytest.mark.asyncio
async def test_chat_rejects_datasource_from_another_agent(monkeypatch):
    async def fake_load_history(agent_id, session_id, limit=5, **kwargs):
        return []

    monkeypatch.setattr(main, "load_history", fake_load_history)
    monkeypatch.setattr(main, "get_graph", lambda: FakeGraph())
    monkeypatch.setattr(
        main,
        "get_datasource_service",
        lambda: FakeDatasourceService(),
        raising=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await main.chat(
            {
                "question": "查余额",
                "agent_id": 2,
                "datasource_id": 7,
                "session_id": "s1",
            },
            current_user=ADMIN_USER,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_chat_resolves_default_agent_datasource_when_request_omits_datasource(monkeypatch):
    async def fake_load_history(agent_id, session_id, limit=5, **kwargs):
        return []

    saved_turns = []

    async def fake_save_turn(agent_id, session_id, question, answer, sql, sql_result, **kwargs):
        saved_turns.append({"agent_id": agent_id, "user": kwargs.get("user")})

    async def fake_prepare_chat_state(**kwargs):
        return {
            "question": kwargs["question"],
            "agent_id": kwargs["agent_id"],
            "user_id": kwargs["user"].id,
            "datasource_id": kwargs["datasource_id"],
            "session_id": kwargs["session_id"],
            "trace_id": kwargs["trace_id"],
            "chat_history": kwargs["history"],
        }

    graph = FakeGraph()
    monkeypatch.setattr(main, "load_history", fake_load_history)
    monkeypatch.setattr(main, "save_turn", fake_save_turn)
    monkeypatch.setattr(main, "prepare_chat_state", fake_prepare_chat_state)
    monkeypatch.setattr(main, "get_graph", lambda: graph)
    monkeypatch.setattr(
        main,
        "get_datasource_service",
        lambda: FakeDatasourceService(),
        raising=False,
    )

    response = await main.chat(
        {
            "question": "查余额",
            "agent_id": 1,
            "session_id": "s1",
        },
        current_user=ADMIN_USER,
    )

    assert response["answer"] == "ok"
    assert graph.seen_state["datasource_id"] == 7
    assert saved_turns[0]["user"].id == ADMIN_USER.id


@pytest.mark.asyncio
async def test_non_query_chat_does_not_require_datasource(monkeypatch):
    class NoDatasourceService:
        async def list_by_agent(self, agent_id):
            return []

    monkeypatch.setattr(main, "get_datasource_service", lambda: NoDatasourceService())

    assert await main.resolve_chat_datasource_access(1, None, "你好", []) is None


@pytest.mark.asyncio
async def test_data_query_still_requires_datasource_when_omitted(monkeypatch):
    class NoDatasourceService:
        async def list_by_agent(self, agent_id):
            return []

    monkeypatch.setattr(main, "get_datasource_service", lambda: NoDatasourceService())

    with pytest.raises(HTTPException) as exc_info:
        await main.resolve_chat_datasource_access(1, None, "查询申请笔数", [])

    assert exc_info.value.status_code == 400
