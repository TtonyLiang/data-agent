import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import twin_runtime_service
from app.services.ontology_service import _stable_release_definition
from app.services.twin_runtime_service import TwinRuntimeService


class FakeDB:
    def __init__(self):
        self.insert = None
        self.updates = []
        self.rows = []

    async def execute_insert(self, sql, params):
        self.insert = (sql, params)
        return 17

    async def execute_query(self, sql, params):
        if sql.startswith("UPDATE twin_sync_run"):
            self.updates.append((sql, params))
            return []
        if "WHERE id = :id" in sql:
            return self.rows[:1]
        return self.rows


class SourceDB:
    def __init__(self):
        self.queries = []

    async def execute_query(self, sql, params=None):
        self.queries.append((sql, params or {}))
        if "COUNT(*)" in sql:
            return [{"count": 1}]
        return [{"loan_id": 1, "loan_no": "LN-1", "balance": 100}]


class PreviewManagementDB(FakeDB):
    async def execute_query(self, sql, params):
        if sql.startswith("SELECT * FROM ontology_object"):
            return []
        return await super().execute_query(sql, params)


class PreviewOntology:
    async def _load_object_permission_context(self, domain, access_agent_id):
        assert domain["datasource_id"] == 8
        assert access_agent_id == 7
        return 8, {"loan_account_indicator": True}, {}

    async def list_object_types(self, domain_id):
        return [
            {
                "id": 12,
                "domain_id": domain_id,
                "object_key": "LoanAccount",
                "name": "贷款账户",
                "primary_property": "loan_id",
                "display_property": "loan_no",
                "sync_enabled": True,
                "source_query": (
                    "SELECT loan_id, loan_no, balance "
                    "FROM loan_account_indicator ORDER BY loan_id"
                ),
                "properties": [
                    {
                        "property_key": "loan_id",
                        "name": "贷款ID",
                        "data_type": "integer",
                        "required": True,
                        "unique": True,
                        "default_value": None,
                    },
                    {
                        "property_key": "loan_no",
                        "name": "贷款编号",
                        "data_type": "string",
                        "required": True,
                        "unique": False,
                        "default_value": None,
                    },
                    {
                        "property_key": "balance",
                        "name": "余额",
                        "data_type": "number",
                        "required": True,
                        "unique": False,
                        "default_value": None,
                    },
                ],
            }
        ]

    async def list_link_types(self, domain_id):
        return []

    def _validated_source_query(self, source_query):
        return source_query

    @staticmethod
    def _validate_sync_key_permissions(*_args):
        return None

    @staticmethod
    def _permission_metadata(row, object_type):
        return {
            **row,
            "_permission_source_query": object_type.get("source_query"),
            "_permission_primary_property": object_type.get("primary_property"),
            "_permission_display_property": object_type.get("display_property"),
        }

    @staticmethod
    def _protect_object_rows(rows, _permission_context):
        return rows


class PreviewPermission:
    async def validate_sql_access(self, agent_id, datasource_id, sql):
        assert (agent_id, datasource_id) == (7, 8)
        assert sql.startswith("SELECT")
        return True, "OK"

    async def get_result_column_policies(self, agent_id, datasource_id, sql):
        assert (agent_id, datasource_id) == (7, 8)
        assert sql.startswith("SELECT")
        return {}

    async def mask_rows(self, *_args, **_kwargs):
        raise AssertionError("preview must calculate object identity from raw source rows")


@pytest.mark.asyncio
async def test_twin_sync_run_lifecycle(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(twin_runtime_service, "get_management_db", lambda: db)
    service = TwinRuntimeService()

    created = await service.create_run(
        domain_id=4,
        datasource_id=8,
        object_type_id=12,
        model_release_id=3,
        caller_agent_id=7,
        created_by=2,
        page=1,
        page_size=100,
        sync_links=True,
        dry_run=True,
        trace_id="sync_test",
    )

    assert created == {
        "id": 17,
        "trace_id": "sync_test",
        "status": "running",
        "dry_run": True,
    }
    assert db.insert[1]["model_release_id"] == 3
    assert db.insert[1]["dry_run"] == 1

    await service.complete_run(
        17,
        status="partial",
        statistics={"read": 10, "created": 2, "errors": ["bad row"]},
        error_summary="bad row",
    )
    update = db.updates[0][1]
    assert update["status"] == "partial"
    assert json.loads(update["statistics"])["created"] == 2


@pytest.mark.asyncio
async def test_twin_sync_run_normalizes_rows(monkeypatch):
    db = FakeDB()
    db.rows = [
        {
            "id": 17,
            "domain_id": 4,
            "dry_run": 1,
            "sync_links": 0,
            "statistics_json": '{"read": 5}',
        }
    ]
    monkeypatch.setattr(twin_runtime_service, "get_management_db", lambda: db)

    row = await TwinRuntimeService().get_run(4, 17)

    assert row["dry_run"] is True
    assert row["sync_links"] is False
    assert row["statistics_json"] == {"read": 5}


@pytest.mark.asyncio
async def test_preview_sync_reads_without_writing_objects(monkeypatch):
    management_db = PreviewManagementDB()
    source_db = SourceDB()
    monkeypatch.setattr(twin_runtime_service, "get_management_db", lambda: management_db)
    monkeypatch.setattr(
        twin_runtime_service,
        "get_semantic_runtime_service",
        lambda: SimpleNamespace(
            get_domain=lambda domain_id: _async_value(
                SimpleNamespace(id=domain_id, datasource_id=8)
            )
        ),
    )
    monkeypatch.setattr(
        twin_runtime_service, "get_ontology_service", lambda: PreviewOntology()
    )
    monkeypatch.setattr(
        twin_runtime_service, "get_permission_service", lambda: PreviewPermission()
    )
    monkeypatch.setattr(
        twin_runtime_service,
        "get_datasource_db",
        lambda datasource_id: _async_value(source_db),
    )

    result = await TwinRuntimeService().preview_sync(
        domain_id=4,
        access_agent_id=7,
        object_type_id=12,
        page=1,
        page_size=100,
    )

    assert result["dry_run"] is True
    assert result["types"][0]["created"] == 1
    assert result["objects"][0]["outcome"] == "created"
    assert management_db.insert is None
    assert management_db.updates == []


@pytest.mark.asyncio
async def test_preview_sync_rejects_inactive_domain(monkeypatch):
    monkeypatch.setattr(
        twin_runtime_service,
        "get_semantic_runtime_service",
        lambda: SimpleNamespace(
            get_domain=lambda domain_id: _async_value(
                SimpleNamespace(id=domain_id, datasource_id=8, status="inactive")
            )
        ),
    )

    with pytest.raises(ValueError, match="业务领域已停用"):
        await TwinRuntimeService().preview_sync(
            domain_id=4,
            access_agent_id=7,
            object_type_id=12,
            page=1,
            page_size=100,
        )


@pytest.mark.asyncio
async def test_sync_uses_active_release_when_live_definition_drifts(monkeypatch):
    service = TwinRuntimeService()
    snapshot_json = {"version": 1, "domain": {"datasource_id": 8}}
    semantic_hash = twin_runtime_service.canonical_sha256(snapshot_json)
    definition = {
        "format": "wenqu-ontology",
        "version": 1,
        "domain": {"domain_key": "loan_risk"},
        "object_types": [],
        "link_types": [],
        "action_types": [],
    }
    ontology_hash = twin_runtime_service._content_hash(definition)
    release = {
        "id": 3,
        "version": 2,
        "semantic_snapshot_id": 8,
        "ontology_release_id": 9,
        "semantic_snapshot_hash": semantic_hash,
        "ontology_definition_hash": ontology_hash,
        "model_hash": twin_runtime_service.canonical_sha256(
            {
                "format": "wenqu-enterprise-model-release/v1",
                "semantic_snapshot_hash": semantic_hash,
                "ontology_definition_hash": ontology_hash,
            }
        ),
    }
    model_release_service = AsyncMock()
    model_release_service.get_active_release.return_value = release
    monkeypatch.setattr(
        twin_runtime_service,
        "get_model_release_service",
        lambda: model_release_service,
    )
    runtime_service = AsyncMock()
    runtime_service.get_snapshot.return_value = {"snapshot_json": snapshot_json}
    monkeypatch.setattr(
        twin_runtime_service,
        "get_semantic_runtime_service",
        lambda: runtime_service,
    )
    ontology = AsyncMock()
    ontology.export_bundle.return_value = {
        "format": "wenqu-ontology",
        "version": 1,
        "domain": {"domain_key": "changed"},
        "object_types": [],
        "link_types": [],
        "action_types": [],
    }
    monkeypatch.setattr(twin_runtime_service, "get_ontology_service", lambda: ontology)
    db = FakeDB()
    db.rows = [
        {
            "id": 9,
            "definition_json": json.dumps(definition, ensure_ascii=False),
            "definition_hash": ontology_hash,
        }
    ]
    monkeypatch.setattr(twin_runtime_service, "get_management_db", lambda: db)

    result = await service._validated_active_release(4, datasource_id=8)

    assert result["definition_mode"] == "active_release_immutable"
    assert result["ontology_definition"] == definition
    ontology.export_bundle.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_accepts_legacy_release_when_runtime_exposes_relation_key_arrays(monkeypatch):
    service = TwinRuntimeService()
    snapshot_json = {"version": 1, "domain": {"datasource_id": 8}}
    semantic_hash = twin_runtime_service.canonical_sha256(snapshot_json)
    legacy_bundle = {
        "format": "wenqu-ontology",
        "version": 1,
        "domain": {"domain_key": "loan_risk"},
        "object_types": [],
        "link_types": [
            {
                "link_key": "customer_has_application",
                "source_object_key": "Customer",
                "target_object_key": "LoanApplication",
                "source_property": "tenant_id,customer_id",
                "target_property": "tenant_id,customer_id",
            }
        ],
        "action_types": [],
    }
    live_bundle = copy.deepcopy(legacy_bundle)
    live_bundle["link_types"][0].update(
        {
            "source_property": "tenant_id",
            "target_property": "tenant_id",
            "source_property_keys": ["tenant_id", "customer_id"],
            "target_property_keys": ["tenant_id", "customer_id"],
        }
    )
    ontology_hash = twin_runtime_service._content_hash(
        _stable_release_definition(legacy_bundle)
    )
    release = {
        "id": 3,
        "version": 2,
        "semantic_snapshot_id": 8,
        "ontology_release_id": 9,
        "semantic_snapshot_hash": semantic_hash,
        "ontology_definition_hash": ontology_hash,
        "model_hash": twin_runtime_service.canonical_sha256(
            {
                "format": "wenqu-enterprise-model-release/v1",
                "semantic_snapshot_hash": semantic_hash,
                "ontology_definition_hash": ontology_hash,
            }
        ),
    }
    model_release_service = AsyncMock()
    model_release_service.get_active_release.return_value = release
    monkeypatch.setattr(
        twin_runtime_service,
        "get_model_release_service",
        lambda: model_release_service,
    )
    runtime_service = AsyncMock()
    runtime_service.get_snapshot.return_value = {"snapshot_json": snapshot_json}
    monkeypatch.setattr(
        twin_runtime_service,
        "get_semantic_runtime_service",
        lambda: runtime_service,
    )
    ontology = AsyncMock()
    ontology.export_bundle.return_value = live_bundle
    monkeypatch.setattr(twin_runtime_service, "get_ontology_service", lambda: ontology)
    db = FakeDB()
    db.rows = [
        {
            "id": 9,
            "definition_json": json.dumps(legacy_bundle, ensure_ascii=False),
            "definition_hash": ontology_hash,
        }
    ]
    monkeypatch.setattr(twin_runtime_service, "get_management_db", lambda: db)

    result = await service._validated_active_release(4, datasource_id=8)

    assert result["ontology_definition_hash"] == ontology_hash
    assert result["definition_mode"] == "active_release_immutable"
    assert result["ontology_definition"] == legacy_bundle


@pytest.mark.asyncio
async def test_sync_rejects_datasource_drift_from_active_snapshot(monkeypatch):
    service = TwinRuntimeService()
    snapshot_json = {"version": 1, "domain": {"datasource_id": 99}}
    semantic_hash = twin_runtime_service.canonical_sha256(snapshot_json)
    model_release_service = AsyncMock()
    model_release_service.get_active_release.return_value = {
        "id": 3,
        "version": 2,
        "semantic_snapshot_id": 8,
        "ontology_release_id": 9,
        "semantic_snapshot_hash": semantic_hash,
        "ontology_definition_hash": "b" * 64,
        "model_hash": "c" * 64,
    }
    runtime_service = AsyncMock()
    runtime_service.get_snapshot.return_value = {"snapshot_json": snapshot_json}
    monkeypatch.setattr(
        twin_runtime_service,
        "get_model_release_service",
        lambda: model_release_service,
    )
    monkeypatch.setattr(
        twin_runtime_service,
        "get_semantic_runtime_service",
        lambda: runtime_service,
    )

    with pytest.raises(ValueError, match="当前数据源已偏离激活企业模型版本"):
        await service._validated_active_release(4, datasource_id=8)


@pytest.mark.asyncio
async def test_all_object_types_failed_marks_run_failed(monkeypatch):
    service = TwinRuntimeService()
    result = {
        "types": [{"read": 0, "created": 0, "updated": 0, "unchanged": 0,
                   "skipped": 0, "errors": ["source unavailable"], "objects": []}],
        "objects": [],
        "links_synced": 0,
        "has_errors": True,
    }
    complete = await _prepare_execute_sync(monkeypatch, service, result)

    await service.execute_sync(
        domain_id=4,
        access_agent_id=7,
        created_by=1,
        object_type_id=None,
        page=1,
        page_size=100,
        sync_links=False,
        dry_run=False,
    )

    create_kwargs = service.create_run.await_args.kwargs
    assert create_kwargs["model_release_id"] == 3
    assert create_kwargs["release_lineage"]["definition_mode"] == (
        "active_release_immutable"
    )
    assert complete.await_args.kwargs["status"] == "failed"
    assert complete.await_args.kwargs["statistics"]["model_release"]["id"] == 3


@pytest.mark.asyncio
async def test_missing_active_release_does_not_create_run(monkeypatch):
    service = TwinRuntimeService()
    runtime_service = AsyncMock()
    runtime_service.get_domain.return_value = SimpleNamespace(id=4, datasource_id=8)
    monkeypatch.setattr(
        twin_runtime_service,
        "get_semantic_runtime_service",
        lambda: runtime_service,
    )
    datasource_service = AsyncMock()
    datasource_service.belongs_to_agent.return_value = True
    monkeypatch.setattr(
        twin_runtime_service,
        "get_datasource_service",
        lambda: datasource_service,
    )
    monkeypatch.setattr(
        service,
        "_validated_active_release",
        AsyncMock(side_effect=ValueError("当前业务领域没有激活的企业模型版本")),
    )
    create_run = AsyncMock()
    monkeypatch.setattr(service, "create_run", create_run)

    with pytest.raises(ValueError, match="没有激活"):
        await service.execute_sync(
            domain_id=4,
            access_agent_id=7,
            created_by=1,
            object_type_id=None,
            page=1,
            page_size=100,
            sync_links=False,
            dry_run=False,
        )

    create_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_relationship_failure_after_object_sync_marks_run_partial(monkeypatch):
    service = TwinRuntimeService()
    result = {
        "types": [{"read": 1, "created": 1, "updated": 0, "unchanged": 0,
                   "skipped": 0, "errors": [], "objects": [{"id": 5}]}],
        "objects": [{"id": 5}],
        "links_synced": 0,
        "has_errors": False,
    }
    complete, ontology = await _prepare_execute_sync(
        monkeypatch, service, result, include_ontology=True
    )
    ontology.sync_objects_from_datasource.return_value = {
        **result,
        "relationship_errors": ["link join failed"],
        "has_errors": True,
    }

    response = await service.execute_sync(
        domain_id=4,
        access_agent_id=7,
        created_by=1,
        object_type_id=None,
        page=1,
        page_size=100,
        sync_links=True,
        dry_run=False,
    )

    assert complete.await_args.kwargs["status"] == "partial"
    assert response["result"]["relationship_errors"]
    assert ontology.sync_objects_from_datasource.await_args.kwargs["release_definition"] == {
        "format": "wenqu-ontology",
        "version": 1,
        "domain": {"domain_key": "loan_risk"},
        "object_types": [],
        "link_types": [],
        "action_types": [],
    }


@pytest.mark.asyncio
async def test_list_runs_marks_stale_running_records_failed(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(twin_runtime_service, "get_management_db", lambda: db)

    await TwinRuntimeService().list_runs(4)

    stale_update = next(
        sql for sql, _ in db.updates if "status = 'failed'" in sql
    )
    assert "status = 'running'" in stale_update
    assert "DATE_SUB" in stale_update


async def _prepare_execute_sync(
    monkeypatch,
    service,
    result,
    *,
    include_ontology=False,
):
    runtime_service = AsyncMock()
    runtime_service.get_domain.return_value = SimpleNamespace(id=4, datasource_id=8)
    monkeypatch.setattr(
        twin_runtime_service,
        "get_semantic_runtime_service",
        lambda: runtime_service,
    )
    datasource_service = AsyncMock()
    datasource_service.belongs_to_agent.return_value = True
    monkeypatch.setattr(
        twin_runtime_service,
        "get_datasource_service",
        lambda: datasource_service,
    )
    monkeypatch.setattr(
        service,
        "_validated_active_release",
        AsyncMock(
            return_value={
                "id": 3,
                "version": 2,
                "model_hash": "c" * 64,
                "semantic_snapshot_id": 8,
                "semantic_snapshot_hash": "a" * 64,
                "ontology_release_id": 9,
                "ontology_definition_hash": "b" * 64,
                "definition_mode": "active_release_immutable",
                "ontology_definition": {
                    "format": "wenqu-ontology",
                    "version": 1,
                    "domain": {"domain_key": "loan_risk"},
                    "object_types": [],
                    "link_types": [],
                    "action_types": [],
                },
            }
        ),
    )
    monkeypatch.setattr(
        service,
        "create_run",
        AsyncMock(return_value={"id": 17, "status": "running"}),
    )
    complete = AsyncMock()
    monkeypatch.setattr(service, "complete_run", complete)
    monkeypatch.setattr(
        service,
        "get_run",
        AsyncMock(return_value={"id": 17, "status": "completed"}),
    )
    ontology = AsyncMock()
    ontology.sync_objects_from_datasource.return_value = result
    ontology._sync_links_for_objects.return_value = 2
    monkeypatch.setattr(twin_runtime_service, "get_ontology_service", lambda: ontology)
    return (complete, ontology) if include_ontology else complete


async def _async_value(value):
    return value
