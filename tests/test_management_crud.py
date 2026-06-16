import pytest

from app.api import agent as agent_api
from app.api import datasource as datasource_api
from app.api import model_config as model_config_api
from app.models.agent import AgentCreate
from app.models import datasource as datasource_model
from app.models.model_config import ModelConfigCreate
from app.services.datasource_service import DatasourceService


class RecordingDB:
    def __init__(self):
        self.queries: list[tuple[str, dict | None]] = []

    async def execute_query(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params))
        if sql.startswith("SELECT * FROM agent"):
            return [
                {
                    "id": params["id"],
                    "name": "编辑后智能体",
                    "description": "updated",
                    "llm_provider": "ollama",
                    "llm_model": "qwen3:32b",
                    "api_key": "secret",
                    "api_key_enabled": 0,
                }
            ]
        if sql.startswith("SELECT a."):
            return [
                {
                    "id": params["id"],
                    "name": "编辑后智能体",
                    "description": "updated",
                    "chat_model_config_id": 11,
                    "embedding_model_config_id": 12,
                    "semantic_domain_id": 21,
                    "chat_model_config_name": "Chat",
                    "embedding_model_config_name": "Embedding",
                    "semantic_domain_name": "贷款风控",
                    "semantic_domain_key": "loan_risk",
                    "llm_provider": "ollama",
                    "llm_model": "qwen3:32b",
                    "api_key": "secret",
                    "api_key_enabled": 0,
                }
            ]
        return []


@pytest.mark.asyncio
async def test_update_agent_updates_fields_and_does_not_return_api_key(monkeypatch):
    db = RecordingDB()
    monkeypatch.setattr(agent_api, "get_management_db", lambda: db)

    class FakeDatasourceService:
        async def set_agent_datasources(self, agent_id, datasource_ids):
            return datasource_ids

    monkeypatch.setattr(agent_api, "get_datasource_service", lambda: FakeDatasourceService())

    response = await agent_api.update_agent(
        9,
        AgentCreate(
            name="编辑后智能体",
            description="updated",
            chat_model_config_id=11,
            embedding_model_config_id=12,
            semantic_domain_id=21,
            datasource_ids=[3, 4],
        ),
    )

    update_sql, update_params = next((sql, params) for sql, params in db.queries if "UPDATE agent" in sql)
    assert "chat_model_config_id" in update_sql
    assert "semantic_domain_id" in update_sql
    assert update_params["chat_model_config_id"] == 11
    assert update_params["embedding_model_config_id"] == 12
    assert update_params["semantic_domain_id"] == 21
    assert response["agent"]["name"] == "编辑后智能体"
    assert response["agent"]["semantic_domain_name"] == "贷款风控"
    assert "api_key" not in response["agent"]


@pytest.mark.asyncio
async def test_update_datasource_omits_password_when_blank(monkeypatch):
    db = RecordingDB()
    monkeypatch.setattr("app.services.datasource_service.get_management_db", lambda: db)

    await DatasourceService().update(
        7,
        datasource_model.DatasourceUpdate(
            agent_id=1,
            name="业务库",
            db_type="mysql",
            host="127.0.0.1",
            port=3306,
            username="root",
            password="",
            database_name="business_db",
        ),
    )

    update_sql, params = db.queries[0]
    assert "password" not in update_sql
    assert "pwd" not in (params or {})


@pytest.mark.asyncio
async def test_delete_datasource_removes_metadata_before_datasource(monkeypatch):
    db = RecordingDB()
    monkeypatch.setattr("app.services.datasource_service.get_management_db", lambda: db)

    await DatasourceService().delete(7)

    statements = [sql for sql, _ in db.queries]
    assert any("DELETE FROM semantic_domain" in sql for sql in statements)
    assert any("DELETE FROM meta_column" in sql for sql in statements)
    assert any("DELETE FROM meta_table" in sql for sql in statements)
    assert "DELETE FROM datasource WHERE id = :id" in statements[-1]


@pytest.mark.asyncio
async def test_datasource_access_uses_agent_datasource_join(monkeypatch):
    db = RecordingDB()

    async def execute_query(sql: str, params: dict | None = None):
        db.queries.append((sql, params))
        if "FROM agent_datasource" in sql:
            return [{"datasource_id": 7}]
        return []

    db.execute_query = execute_query
    monkeypatch.setattr("app.services.datasource_service.get_management_db", lambda: db)

    assert await DatasourceService().belongs_to_agent(7, 2) is True
    assert "agent_datasource" in db.queries[0][0]


@pytest.mark.asyncio
async def test_datasource_api_exposes_update_and_delete(monkeypatch):
    class FakeDatasource:
        def __init__(self, ds_id, name):
            self.ds_id = ds_id
            self.name = name

        def model_dump(self, exclude=None):
            data = {"id": self.ds_id, "name": self.name, "password": "secret"}
            for key in exclude or set():
                data.pop(key, None)
            return data

    class FakeDatasourceService:
        async def update(self, ds_id, ds):
            return FakeDatasource(ds_id, ds.name)

        async def delete(self, ds_id):
            return True

    monkeypatch.setattr(datasource_api, "get_datasource_service", lambda: FakeDatasourceService())

    updated = await datasource_api.update_datasource(
        3,
        datasource_model.DatasourceUpdate(
            agent_id=1,
            name="编辑后数据源",
            db_type="mysql",
            host="127.0.0.1",
            port=3306,
            username="root",
            password="",
            database_name="business_db",
        ),
    )
    deleted = await datasource_api.delete_datasource(3)

    assert updated["datasource"]["name"] == "编辑后数据源"
    assert deleted["message"] == "删除成功"


@pytest.mark.asyncio
async def test_model_config_api_does_not_return_api_key(monkeypatch):
    class FakeModelConfigService:
        async def create(self, config):
            return 8

        async def list(self, model_type=None):
            return [
                {
                    "id": 8,
                    "name": "默认向量模型",
                    "model_type": "embedding",
                    "provider": "openai-compatible",
                    "base_url": "https://example.test/v1",
                    "model_name": "embedding-3",
                    "api_key_enabled": 1,
                    "embedding_dimension": 1024,
                }
            ]

    monkeypatch.setattr(model_config_api, "get_model_config_service", lambda: FakeModelConfigService())

    created = await model_config_api.create_model_config(
        ModelConfigCreate(
            name="默认向量模型",
            model_type="embedding",
            provider="openai-compatible",
            base_url="https://example.test/v1",
            model_name="embedding-3",
            api_key="secret",
            api_key_enabled=True,
            embedding_dimension=1024,
        )
    )
    listed = await model_config_api.list_model_configs(model_type="embedding")

    assert created["id"] == 8
    assert listed["configs"][0]["model_type"] == "embedding"
    assert "api_key" not in listed["configs"][0]
