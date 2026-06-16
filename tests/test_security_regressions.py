import pytest
from fastapi import HTTPException

from app import main
from app.api import agent as agent_api
from app.api import datasource as datasource_api


class FakeDatasource:
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
    async def ainvoke(self, state):
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

    response = await datasource_api.list_datasources(agent_id=1)

    assert "password" not in response["datasources"][0]
    assert response["datasources"][0]["username"] == "root"


@pytest.mark.asyncio
async def test_agent_list_does_not_return_api_key(monkeypatch):
    monkeypatch.setattr(agent_api, "get_management_db", lambda: FakeManagementDB())

    response = await agent_api.list_agents()

    assert "api_key" not in response["agents"][0]
    assert response["agents"][0]["api_key_enabled"] == 1


@pytest.mark.asyncio
async def test_chat_rejects_datasource_from_another_agent(monkeypatch):
    async def fake_load_history(agent_id, session_id, limit=5):
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
            }
        )

    assert exc_info.value.status_code == 403
