import asyncio

import pytest

from app.api import agent as agent_api
from app.api import semantic as semantic_api
from app.db import migrations
from app.models.agent import AgentDomainBindingUpdate
from app.models.knowledge import SemanticConcept, SemanticDomain, SemanticRuntime
from app.models.user import PublicUser
from app.services import semantic_runtime, workspace_service
from app.services.semantic_runtime import SemanticRuntimeService
from app.services.workspace_service import WorkspaceService


class BindingDB:
    def __init__(self, domain_ids: set[int] | None = None):
        self.domain_ids = domain_ids or set()
        self.queries: list[tuple[str, dict | None]] = []
        self.transactions: list[list[tuple[str, dict | None]]] = []

    async def execute_query(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params))
        if sql.startswith("SELECT id FROM agent WHERE"):
            return [{"id": params["agent_id"]}]
        if sql.startswith("SELECT id FROM semantic_domain WHERE id IN"):
            requested = {int(value) for value in (params or {}).values()}
            return [{"id": domain_id} for domain_id in sorted(requested & self.domain_ids)]
        return []

    async def execute_transaction(self, statements):
        self.transactions.append(list(statements))


@pytest.mark.asyncio
async def test_agent_domain_binding_is_many_to_many_and_keeps_default(monkeypatch):
    db = BindingDB({5, 7})
    monkeypatch.setattr(semantic_runtime, "get_management_db", lambda: db)

    result = await SemanticRuntimeService().set_agent_domains(
        agent_id=3,
        domain_ids=[5],
        default_domain_id=7,
    )

    assert result == {"domain_ids": [5, 7], "default_domain_id": 7}
    statements = db.transactions[0]
    assert statements[0] == (
        "UPDATE semantic_domain SET agent_id = NULL WHERE agent_id = :agent_id",
        {"agent_id": 3},
    )
    assert statements[1][0] == "DELETE FROM agent_semantic_domain WHERE agent_id = :agent_id"
    inserts = [params for sql, params in statements if sql.startswith("INSERT INTO")]
    assert inserts == [
        {"agent_id": 3, "domain_id": 5},
        {"agent_id": 3, "domain_id": 7},
    ]
    assert statements[-1] == (
        "UPDATE agent SET semantic_domain_id = :default_domain_id WHERE id = :agent_id",
        {"agent_id": 3, "default_domain_id": 7},
    )


@pytest.mark.asyncio
async def test_agent_domain_binding_rejects_unknown_domain(monkeypatch):
    db = BindingDB({5})
    monkeypatch.setattr(semantic_runtime, "get_management_db", lambda: db)

    with pytest.raises(ValueError, match="企业业务领域不存在: 7"):
        await SemanticRuntimeService().set_agent_domains(3, [5, 7], 5)

    assert db.transactions == []


@pytest.mark.asyncio
async def test_list_agent_domains_reads_consumer_binding_not_legacy_owner(monkeypatch):
    class DomainListDB:
        async def execute_query(self, sql: str, params: dict | None = None):
            assert "JOIN agent_semantic_domain" in sql
            assert params == {"aid": 3}
            return [
                {
                    "id": 7,
                    "workspace_id": 1,
                    "agent_id": None,
                    "domain_key": "loan_risk",
                    "name": "贷款风控",
                }
            ]

    monkeypatch.setattr(semantic_runtime, "get_management_db", lambda: DomainListDB())

    domains = await SemanticRuntimeService().list_domains(3)

    assert [domain.id for domain in domains] == [7]
    assert domains[0].agent_id is None


@pytest.mark.asyncio
async def test_agent_domain_binding_api_exposes_stable_contract(monkeypatch):
    class UserService:
        async def can_access_agent(self, user, agent_id):
            return user.id == 8 and agent_id == 3

    class SemanticService:
        async def get_agent_domain_binding(self, agent_id):
            return {"domain_ids": [5, 7], "default_domain_id": 7}

        async def set_agent_domains(self, agent_id, domain_ids, default_domain_id):
            assert agent_id == 3
            assert domain_ids == [5]
            assert default_domain_id == 7
            return {"domain_ids": [5, 7], "default_domain_id": 7}

    service = SemanticService()
    monkeypatch.setattr(agent_api, "get_user_service", lambda: UserService())
    monkeypatch.setattr(agent_api, "get_semantic_runtime_service", lambda: service)
    user = PublicUser(id=8, username="reader", role="user", status="active")

    read_result = await agent_api.get_agent_domain_ids(3, user)
    write_result = await agent_api.update_agent_domain_ids(
        3,
        AgentDomainBindingUpdate(domain_ids=[5], default_domain_id=7),
    )

    assert read_result == {"domain_ids": [5, 7], "default_domain_id": 7}
    assert write_result == {
        "domain_ids": [5, 7],
        "default_domain_id": 7,
        "message": "企业业务领域绑定已保存",
    }


@pytest.mark.asyncio
async def test_runtime_build_resolves_agent_from_domain_server_side(monkeypatch):
    class SemanticService:
        def __init__(self):
            self.resolve_calls = []
            self.build_calls = []

        async def resolve_domain_agent(self, domain_id, preferred_agent_id):
            self.resolve_calls.append((domain_id, preferred_agent_id))
            return 4

        async def build_runtime(self, **kwargs):
            self.build_calls.append(kwargs)
            return SemanticRuntime(
                domain=SemanticDomain(
                    id=7,
                    workspace_id=1,
                    agent_id=None,
                    domain_key="loan_risk",
                    name="贷款风控",
                )
            )

    service = SemanticService()
    monkeypatch.setattr(semantic_api, "get_semantic_runtime_service", lambda: service)
    admin = PublicUser(id=1, username="admin", role="admin", status="active")

    response = await semantic_api.build_runtime({"domain_id": 7}, admin)

    assert service.resolve_calls == [(7, None)]
    assert service.build_calls[0]["agent_id"] == 4
    assert response["runtime"]["domain"]["id"] == 7


@pytest.mark.asyncio
async def test_vector_sync_updates_every_agent_bound_to_shared_domain(monkeypatch):
    domain = SemanticDomain(
        id=7,
        workspace_id=1,
        agent_id=None,
        datasource_id=42,
        domain_key="loan_risk",
        name="贷款风控",
    )
    runtime = SemanticRuntime(
        domain=domain,
        concepts=[
            SemanticConcept(
                id=11,
                domain_id=7,
                concept_key="customer",
                concept_type="object",
                name="客户",
            )
        ],
    )

    class SemanticService:
        async def get_domain(self, domain_id):
            return domain

        async def get_domain_agent_ids(self, domain_id):
            return [3, 4]

        async def build_runtime(self, **kwargs):
            assert kwargs["agent_id"] == 3
            return runtime

    class EmbeddingService:
        def __init__(self):
            self.agent_ids = []

        async def embed_texts(self, texts, agent_id=None):
            self.agent_ids.append(agent_id)
            return [[float(agent_id), 0.1] for _ in texts]

    class VectorStore:
        def __init__(self):
            self.deleted = []
            self.inserted = []

        def delete_collection(self, agent_id, domain_id=None):
            self.deleted.append((agent_id, domain_id))

        def insert(self, agent_id, records, domain_id=None):
            self.inserted.append((agent_id, domain_id, records))

    embedding_service = EmbeddingService()
    vector_store = VectorStore()
    monkeypatch.setattr(
        semantic_api,
        "get_semantic_runtime_service",
        lambda: SemanticService(),
    )
    monkeypatch.setattr(semantic_api, "get_embedding_service", lambda: embedding_service)
    monkeypatch.setattr(semantic_api, "get_vector_store", lambda: vector_store)
    admin = PublicUser(id=1, username="admin", role="admin", status="active")

    response = await semantic_api.sync_domain_to_vector(7, admin)

    assert response["agent_ids"] == [3, 4]
    assert embedding_service.agent_ids == [3, 4]
    assert vector_store.deleted == [(3, 7), (3, None), (4, 7), (4, None)]
    assert [(agent_id, domain_id) for agent_id, domain_id, _ in vector_store.inserted] == [
        (3, 7),
        (4, 7),
    ]
    assert vector_store.inserted[0][2][0].agent_id == 3
    assert vector_store.inserted[1][2][0].agent_id == 4


class AtomicDomainDB:
    def __init__(self):
        self.inserts: list[tuple[str, dict | None]] = []
        self.queries: list[tuple[str, dict | None]] = []

    async def execute_insert(self, sql: str, params: dict | None = None):
        self.inserts.append((sql, params))
        await asyncio.sleep(0)
        return 1 if "enterprise_workspace" in sql else 9

    async def execute_query(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params))
        return []


@pytest.mark.asyncio
async def test_repeated_domain_upsert_uses_workspace_unique_atomic_statement(monkeypatch):
    db = AtomicDomainDB()
    monkeypatch.setattr(semantic_runtime, "get_management_db", lambda: db)
    payload = {
        "domain_key": "loan_risk",
        "name": "贷款风控",
        "description": "企业领域资产",
    }

    ids = await asyncio.gather(
        SemanticRuntimeService().upsert_domain(payload),
        SemanticRuntimeService().upsert_domain(payload),
    )

    assert ids == [9, 9]
    domain_inserts = [sql for sql, _ in db.inserts if "INSERT INTO semantic_domain" in sql]
    assert len(domain_inserts) == 2
    assert all("ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)" in sql for sql in domain_inserts)


class DeleteAgentDB:
    def __init__(self):
        self.statements: list[tuple[str, dict | None]] = []

    async def execute_transaction(self, statements):
        self.statements = list(statements)


@pytest.mark.asyncio
async def test_delete_agent_preserves_enterprise_domain_and_ontology(monkeypatch):
    db = DeleteAgentDB()
    monkeypatch.setattr(agent_api, "get_management_db", lambda: db)

    result = await agent_api.delete_agent(4)

    sql = [statement for statement, _ in db.statements]
    assert result["message"] == "删除成功"
    assert "UPDATE semantic_domain SET agent_id = NULL WHERE agent_id = :id" in sql
    assert "DELETE FROM agent_semantic_domain WHERE agent_id = :id" in sql
    assert "DELETE FROM agent WHERE id = :id" == sql[-1]
    assert not any(statement.startswith("DELETE FROM semantic_domain") for statement in sql)
    assert not any("ontology_" in statement for statement in sql)
    assert not any("risk_issue" in statement for statement in sql)


class MigrationDB:
    def __init__(self, duplicate=None):
        self.duplicate = duplicate
        self.queries: list[tuple[str, dict | None]] = []

    async def execute_query(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params))
        if "HAVING COUNT(*) > 1" in sql:
            return [self.duplicate] if self.duplicate else []
        if "INFORMATION_SCHEMA.STATISTICS" in sql:
            if params and params["index_name"] == "uk_agent_domain":
                return [{"INDEX_NAME": "uk_agent_domain"}]
            return []
        return []


@pytest.mark.asyncio
async def test_workspace_domain_unique_migration_stops_on_legacy_duplicates(monkeypatch):
    db = MigrationDB(
        {"workspace_id": 1, "domain_key": "loan_risk", "duplicate_count": 2}
    )
    monkeypatch.setattr(migrations, "get_management_db", lambda: db)

    with pytest.raises(RuntimeError, match="domain_key=loan_risk"):
        await migrations.ensure_workspace_domain_unique_index()

    assert not any("ADD UNIQUE INDEX" in sql for sql, _ in db.queries)


@pytest.mark.asyncio
async def test_workspace_domain_unique_migration_replaces_legacy_unique_index(monkeypatch):
    db = MigrationDB()
    monkeypatch.setattr(migrations, "get_management_db", lambda: db)

    await migrations.ensure_workspace_domain_unique_index()

    sql = [statement for statement, _ in db.queries]
    assert any("ADD UNIQUE INDEX uk_workspace_domain" in statement for statement in sql)
    assert any("DROP INDEX uk_agent_domain" in statement for statement in sql)


@pytest.mark.asyncio
async def test_workspace_migration_removes_orphan_agent_domain_bindings(monkeypatch):
    db = MigrationDB()
    monkeypatch.setattr(migrations, "get_management_db", lambda: db)

    await migrations.cleanup_orphan_agent_domain_bindings()

    assert db.queries == [
        (
            "DELETE asd FROM agent_semantic_domain asd "
            "LEFT JOIN agent a ON a.id = asd.agent_id "
            "LEFT JOIN semantic_domain sd ON sd.id = asd.domain_id "
            "WHERE a.id IS NULL OR sd.id IS NULL",
            None,
        )
    ]


class WorkspaceDB:
    async def execute_query(self, sql: str, params: dict | None = None):
        if "FROM enterprise_workspace ORDER BY" in sql:
            return [
                {
                    "id": 1,
                    "workspace_key": "default",
                    "name": "默认企业空间",
                    "status": "active",
                }
            ]
        if "FROM semantic_domain WHERE workspace_id" in sql:
            return [
                {
                    "id": 9,
                    "workspace_id": params["workspace_id"],
                    "agent_id": None,
                    "domain_key": "loan_risk",
                    "name": "贷款风控",
                }
            ]
        return []


@pytest.mark.asyncio
async def test_default_workspace_is_only_a_logical_domain_container(monkeypatch):
    monkeypatch.setattr(workspace_service, "get_management_db", lambda: WorkspaceDB())
    service = WorkspaceService()

    workspaces = await service.list_workspaces()
    domains = await service.list_domains(1)

    assert workspaces[0].workspace_key == "default"
    assert domains[0].workspace_id == 1
    assert domains[0].agent_id is None
