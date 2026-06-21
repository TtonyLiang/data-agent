import pytest

from app.api import agent as agent_api
from app.api import datasource as datasource_api
from app.api import model_config as model_config_api
from app.models import datasource as datasource_model
from app.models.agent import AgentCreate
from app.models.model_config import ModelConfigCreate, ModelConfigUpdate
from app.services import model_config_service
from app.services.datasource_service import DatasourceService
from app.services.model_config_service import (
    ModelConfigService,
    _public_model_config,
    api_key_expiry_flags,
)
from app.services.secret_service import ENCRYPTED_PREFIX


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

    update_sql, update_params = next(
        (sql, params) for sql, params in db.queries if "UPDATE agent" in sql
    )
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

    monkeypatch.setattr(
        model_config_api, "get_model_config_service", lambda: FakeModelConfigService()
    )

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


@pytest.mark.asyncio
async def test_model_config_update_preserves_api_key_when_form_leaves_it_blank(monkeypatch):
    class FakeModelConfigDB:
        def __init__(self):
            self.row = {
                "id": 8,
                "name": "小米mimo",
                "model_type": "chat",
                "provider": "xiaomi",
                "base_url": "https://api.xiaomimimo.com/v1",
                "model_name": "mimo-v2.5",
                "api_key": "existing-secret",
                "api_key_enabled": 1,
                "embedding_dimension": None,
                "status": "active",
            }
            self.queries: list[tuple[str, dict | None]] = []

        async def execute_query(self, sql: str, params: dict | None = None):
            self.queries.append((sql, params))
            if sql.startswith("SELECT * FROM model_config WHERE id"):
                return [self.row]
            if sql.startswith("UPDATE model_config"):
                self.row = {
                    **self.row,
                    "name": params["name"],
                    "model_type": params["model_type"],
                    "provider": params["provider"],
                    "base_url": params["base_url"],
                    "model_name": params["model_name"],
                    "api_key": params["api_key"],
                    "api_key_enabled": params["api_key_enabled"],
                    "embedding_dimension": params["dimension"],
                    "status": params["status"],
                }
            return []

    db = FakeModelConfigDB()
    monkeypatch.setattr("app.services.model_config_service.get_management_db", lambda: db)

    updated = await ModelConfigService().update(
        8,
        ModelConfigUpdate(
            name="小米mimo",
            model_type="chat",
            provider="xiaomi",
            base_url="https://api.xiaomimimo.com/v1",
            model_name="mimo-v2.5",
            api_key="",
            api_key_enabled=True,
            status="active",
        ),
    )

    update_sql, update_params = next(
        (sql, params) for sql, params in db.queries if sql.startswith("UPDATE model_config")
    )
    assert "api_key = :api_key" in update_sql
    assert update_params["api_key"].startswith(ENCRYPTED_PREFIX)
    assert updated.api_key == "existing-secret"


@pytest.mark.asyncio
async def test_model_config_update_replaces_api_key_when_new_value_is_entered(monkeypatch):
    class FakeModelConfigDB:
        def __init__(self):
            self.row = {
                "id": 8,
                "name": "小米mimo",
                "model_type": "chat",
                "provider": "xiaomi",
                "base_url": "https://api.xiaomimimo.com/v1",
                "model_name": "mimo-v2.5",
                "api_key": "existing-secret",
                "api_key_enabled": 1,
                "embedding_dimension": None,
                "status": "active",
            }
            self.queries: list[tuple[str, dict | None]] = []

        async def execute_query(self, sql: str, params: dict | None = None):
            self.queries.append((sql, params))
            if sql.startswith("SELECT * FROM model_config WHERE id"):
                return [self.row]
            if sql.startswith("UPDATE model_config"):
                self.row = {**self.row, "api_key": params["api_key"]}
            return []

    db = FakeModelConfigDB()
    monkeypatch.setattr("app.services.model_config_service.get_management_db", lambda: db)

    await ModelConfigService().update(
        8,
        ModelConfigUpdate(
            name="小米mimo",
            model_type="chat",
            provider="xiaomi",
            base_url="https://api.xiaomimimo.com/v1",
            model_name="mimo-v2.5",
            api_key="new-secret",
            api_key_enabled=True,
            status="active",
        ),
    )

    update_params = next(
        params for sql, params in db.queries if sql.startswith("UPDATE model_config")
    )
    assert update_params["api_key"].startswith(ENCRYPTED_PREFIX)
    assert update_params["api_key"] != "new-secret"


def test_public_model_config_exposes_configured_flag_without_api_key():
    public = _public_model_config({"id": 8, "name": "小米mimo", "api_key": "secret"})

    assert "api_key" not in public
    assert public["api_key_configured"] is True


def test_api_key_expiry_flags_mark_expired_and_expiring_soon():
    assert api_key_expiry_flags("2000-01-01T00:00:00+00:00") == (True, False)
    assert api_key_expiry_flags("2999-01-01T00:00:00+00:00") == (False, False)


@pytest.mark.asyncio
async def test_model_config_connection_test_requires_key_when_enabled(monkeypatch):
    class FakeModelConfigDB:
        async def execute_query(self, sql: str, params: dict | None = None):
            return [
                {
                    "id": params["id"],
                    "name": "云模型",
                    "model_type": "chat",
                    "provider": "openai-compatible",
                    "base_url": "https://example.com/v1",
                    "model_name": "model",
                    "api_key": "",
                    "api_key_enabled": 1,
                    "embedding_dimension": None,
                    "status": "active",
                }
            ]

    monkeypatch.setattr(model_config_service, "get_management_db", lambda: FakeModelConfigDB())

    result = await ModelConfigService().test_connection(1)

    assert result["ok"] is False
    assert "API Key" in result["message"]


@pytest.mark.asyncio
async def test_model_config_connection_test_uses_openai_compatible_endpoint(monkeypatch):
    class FakeModelConfigDB:
        async def execute_query(self, sql: str, params: dict | None = None):
            return [
                {
                    "id": params["id"],
                    "name": "云模型",
                    "model_type": "chat",
                    "provider": "openai-compatible",
                    "base_url": "https://example.com/v1",
                    "model_name": "model",
                    "api_key": "secret-key",
                    "api_key_enabled": 1,
                    "embedding_dimension": None,
                    "status": "active",
                }
            ]

    calls = []

    class FakeResponse:
        status_code = 200
        text = '{"ok": true}'

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json, headers):
            calls.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(model_config_service, "get_management_db", lambda: FakeModelConfigDB())
    monkeypatch.setattr(model_config_service.httpx, "AsyncClient", FakeAsyncClient)

    result = await ModelConfigService().test_connection(1)

    assert result["ok"] is True
    assert calls[0]["url"] == "https://example.com/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-key"
    assert "secret-key" not in str(result)


@pytest.mark.asyncio
async def test_model_config_embedding_test_uses_provider_adapter(monkeypatch):
    class FakeModelConfigDB:
        async def execute_query(self, sql: str, params: dict | None = None):
            return [
                {
                    "id": params["id"],
                    "name": "豆包向量",
                    "model_type": "embedding",
                    "provider": "字节跳动",
                    "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                    "model_name": "doubao-embedding-text-240515",
                    "api_key": "secret-key",
                    "api_key_enabled": 1,
                    "embedding_dimension": 1024,
                    "status": "active",
                }
            ]

    calls = []

    async def fake_request_embedding(**kwargs):
        calls.append(kwargs)
        return [0.1, 0.2, 0.3], {
            "variant": "volcengine_multimodal_embeddings",
            "status_code": 200,
        }

    monkeypatch.setattr(model_config_service, "get_management_db", lambda: FakeModelConfigDB())
    monkeypatch.setattr(model_config_service, "request_embedding", fake_request_embedding)

    result = await ModelConfigService().test_connection(1)

    assert result["ok"] is True
    assert result["variant"] == "volcengine_multimodal_embeddings"
    assert calls[0]["provider"] == "字节跳动"
    assert calls[0]["base_url"] == "https://ark.cn-beijing.volces.com/api/v3"
    assert calls[0]["model"] == "doubao-embedding-text-240515"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-key"
    assert "secret-key" not in str(result)


@pytest.mark.asyncio
async def test_model_config_list_orders_by_id_asc(monkeypatch):
    class FakeModelConfigDB:
        def __init__(self):
            self.queries: list[tuple[str, dict | None]] = []

        async def execute_query(self, sql: str, params: dict | None = None):
            self.queries.append((sql, params))
            return []

    db = FakeModelConfigDB()
    monkeypatch.setattr("app.services.model_config_service.get_management_db", lambda: db)

    await ModelConfigService().list("chat")
    await ModelConfigService().list()

    assert "ORDER BY id ASC" in db.queries[0][0]
    assert "ORDER BY model_type, id ASC" in db.queries[1][0]
