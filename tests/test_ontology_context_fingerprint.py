import pytest
from sqlalchemy.exc import ProgrammingError

from app.services import task_checkpoint_service
from app.services.task_checkpoint_service import TaskCheckpointService, reconcile_task_state


class FakeOntologyContextDB:
    def __init__(self):
        self.definition_rows = [
            {"kind": "object_type", "item_count": 2, "latest": "2026-08-20T10:00:00"},
            {"kind": "property", "item_count": 7, "latest": "2026-08-20T10:01:00"},
            {"kind": "link_type", "item_count": 1, "latest": "2026-08-20T10:02:00"},
            {"kind": "action_type", "item_count": 3, "latest": "2026-08-20T10:03:00"},
        ]
        self.release = {
            "id": 11,
            "version": 2,
            "definition_hash": "a" * 64,
            "created_at": "2026-08-20T11:00:00",
        }
        self.missing_ontology_tables = False
        self.missing_release_hash = False
        self.queries = []

    async def execute_query(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.queries.append((normalized, params or {}))
        if "FROM agent a" in normalized:
            return [
                {
                    "agent_id": 1,
                    "agent_updated_at": "2026-08-20T09:00:00",
                    "chat_model_config_id": 4,
                    "chat_model_updated_at": "2026-08-20T09:00:00",
                    "embedding_model_config_id": 5,
                    "embedding_model_updated_at": "2026-08-20T09:00:00",
                    "semantic_domain_id": 3,
                    "semantic_domain_updated_at": "2026-08-20T09:00:00",
                    "datasource_id": 7,
                    "datasource_updated_at": "2026-08-20T09:00:00",
                }
            ]
        if "FROM semantic_concept" in normalized:
            return [
                {"kind": "concept", "item_count": 2, "latest": "2026-08-20T09:00:00"}
            ]
        if "FROM meta_table" in normalized:
            return [
                {
                    "table_id": 21,
                    "table_name": "loan_balance",
                    "column_id": 31,
                    "column_name": "balance",
                    "data_type": "decimal",
                }
            ]
        if normalized.startswith("SELECT 'object_type' AS kind"):
            if self.missing_ontology_tables:
                raise ProgrammingError(sql, params or {}, Exception("missing ontology table"))
            return [dict(row) for row in self.definition_rows]
        if normalized.startswith("SELECT id, version, definition_hash, created_at"):
            if self.missing_ontology_tables or self.missing_release_hash:
                raise ProgrammingError(sql, params or {}, Exception("missing release field"))
            return [dict(self.release)] if self.release else []
        if normalized.startswith("SELECT id, version, created_at FROM ontology_release"):
            if self.missing_ontology_tables:
                raise ProgrammingError(sql, params or {}, Exception("missing ontology table"))
            if not self.release:
                return []
            return [
                {
                    "id": self.release["id"],
                    "version": self.release["version"],
                    "created_at": self.release["created_at"],
                }
            ]
        raise AssertionError(f"unexpected SQL: {normalized}")


@pytest.fixture
def ontology_db(monkeypatch):
    db = FakeOntologyContextDB()
    monkeypatch.setattr(task_checkpoint_service, "get_management_db", lambda: db)
    return db


@pytest.mark.asyncio
async def test_same_ontology_version_produces_stable_fingerprint(ontology_db):
    service = TaskCheckpointService()

    first = await service.context(agent_id=1, datasource_id=7)
    second = await service.context(agent_id=1, datasource_id=7)

    assert first["fingerprint"] == second["fingerprint"]
    assert first["ontology_version"]["definitions_available"] is True
    assert first["ontology_version"]["release"] == ontology_db.release
    definition_sql = next(
        sql for sql, _ in ontology_db.queries if sql.startswith("SELECT 'object_type' AS kind")
    )
    for table in (
        "ontology_object_type",
        "ontology_property",
        "ontology_link_type",
        "ontology_action_type",
    ):
        assert table in definition_sql
    assert definition_sql.count("COUNT(*)") == 4
    assert definition_sql.count("MAX(") == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "release_change",
    [
        {"version": 3},
        {"definition_hash": "b" * 64},
    ],
)
async def test_release_version_or_hash_change_updates_fingerprint(ontology_db, release_change):
    service = TaskCheckpointService()
    previous = await service.context(agent_id=1, datasource_id=7)

    ontology_db.release.update(release_change)
    current = await service.context(agent_id=1, datasource_id=7)

    assert current["fingerprint"] != previous["fingerprint"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("item_count", 3),
        ("latest", "2026-08-21T10:00:00"),
    ],
)
async def test_ontology_definition_change_updates_fingerprint(ontology_db, field, value):
    service = TaskCheckpointService()
    previous = await service.context(agent_id=1, datasource_id=7)

    ontology_db.definition_rows[0][field] = value
    current = await service.context(agent_id=1, datasource_id=7)

    assert current["fingerprint"] != previous["fingerprint"]


@pytest.mark.asyncio
async def test_missing_ontology_query_results_are_compatible(ontology_db):
    ontology_db.definition_rows = []
    ontology_db.release = None

    context = await TaskCheckpointService().context(agent_id=1, datasource_id=7)

    assert context["fingerprint"]
    assert context["ontology_version"] == {
        "definitions_available": False,
        "definitions": [],
        "release_available": True,
        "release": None,
    }


@pytest.mark.asyncio
async def test_missing_release_hash_uses_legacy_release_signal(ontology_db):
    ontology_db.missing_release_hash = True

    context = await TaskCheckpointService().context(agent_id=1, datasource_id=7)

    assert context["ontology_version"]["release_available"] is True
    assert context["ontology_version"]["release"] == {
        "id": 11,
        "version": 2,
        "definition_hash": None,
        "created_at": "2026-08-20T11:00:00",
    }


@pytest.mark.asyncio
async def test_missing_ontology_tables_degrade_without_failing_context(ontology_db):
    ontology_db.missing_ontology_tables = True

    context = await TaskCheckpointService().context(agent_id=1, datasource_id=7)

    assert context["fingerprint"]
    assert context["ontology_version"] == {
        "definitions_available": False,
        "definitions": [],
        "release_available": False,
        "release": None,
    }


@pytest.mark.asyncio
async def test_release_change_invalidates_reconcile_dependencies(ontology_db):
    service = TaskCheckpointService()
    previous_context = await service.context(agent_id=1, datasource_id=7)
    ontology_db.release.update({"id": 12, "version": 3, "definition_hash": "b" * 64})
    current_context = await service.context(agent_id=1, datasource_id=7)
    previous_state = {
        "task_id": "task-existing",
        "turn_id": "turn-1",
        "task_revision": 1,
        "task_status": "completed",
        "question": "查询本月贷款余额",
        "task_context": previous_context,
        "query_context": {"query_capabilities": [{"key": "query_loan_balance"}]},
        "query_capability_key": "query_loan_balance",
        "query_capability_validation": {"valid": True},
        "semantic_runtime": {"domain": {"id": 3}},
        "ontology_context": {"release": {"version": 2}},
        "schema_ready": True,
        "logic_form": {"metrics": ["outstanding_balance"]},
        "compiled_query": {"table": "loan_balance"},
        "compiled_sql": "SELECT SUM(balance) FROM loan_balance",
        "sql_text": "SELECT SUM(balance) FROM loan_balance",
        "sql_executed": True,
        "sql_result": [{"outstanding_balance": 100}],
    }

    state = reconcile_task_state(
        previous_state,
        question="重新执行",
        agent_id=1,
        user_id=9,
        session_id="session-1",
        datasource_id=7,
        trace_id="trace-new",
        context=current_context,
        requested_mode="retry",
    )

    assert state["context_invalidated"] is True
    for field in (
        "query_context",
        "query_capability_key",
        "query_capability_validation",
        "logic_form",
        "compiled_query",
        "compiled_sql",
        "sql_text",
        "sql_result",
    ):
        assert field not in state
        assert field in state["invalidated_artifacts"]
