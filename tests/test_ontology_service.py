import json

import pytest
from pydantic import ValidationError

from app.models.ontology import (
    OntologyActionExecutePayload,
    OntologyObjectPayload,
    OntologyObjectTypePayload,
)
from app.services import ontology_service
from app.services.ontology_service import (
    OntologyService,
    _content_hash,
    _normalize_row,
    _stable_release_definition,
    check_preconditions,
    coerce_primary_value,
    validate_action_parameters,
    validate_property_values,
)

PROPERTY_DEFINITIONS = [
    {
        "property_key": "material_id",
        "name": "物料编号",
        "data_type": "string",
        "required": True,
        "default_value": None,
    },
    {
        "property_key": "available_qty",
        "name": "可用数量",
        "data_type": "number",
        "required": True,
        "default_value": None,
    },
    {
        "property_key": "allocation_status",
        "name": "调拨状态",
        "data_type": "string",
        "required": True,
        "default_value": "available",
    },
]


class DBResult:
    def __init__(self, *, lastrowid=0, rowcount=0):
        self.lastrowid = lastrowid
        self.rowcount = rowcount


class RecordingDB:
    def __init__(self):
        self.queries: list[tuple[str, dict]] = []
        self.inserts: list[tuple[str, dict]] = []

    async def execute_query(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params or {}))
        if "FROM ontology_release" in sql and "ORDER BY version DESC LIMIT 1" in sql:
            return [{"id": 3, "version": 2, "definition_hash": "abc123"}]
        if "MAX(version)" in sql:
            return [{"version": 2}]
        return []

    async def execute_insert(self, sql: str, params: dict | None = None):
        self.inserts.append((sql, params or {}))
        return 77

    async def execute_in_transaction(self, callback):
        query_count = len(self.queries)
        insert_count = len(self.inserts)
        try:
            return await callback(self)
        except Exception:
            del self.queries[query_count:]
            del self.inserts[insert_count:]
            raise

    async def execute(self, statement, params: dict | None = None):
        sql = " ".join(str(statement).split())
        if sql.startswith("INSERT INTO ontology_action_run"):
            self.inserts.append((sql, params or {}))
            return DBResult(lastrowid=77, rowcount=1)
        self.queries.append((sql, params or {}))
        if sql.startswith("UPDATE ontology_object"):
            return DBResult(rowcount=1)
        if sql.startswith("UPDATE ontology_action_run"):
            return DBResult(rowcount=1)
        raise AssertionError(f"unexpected transactional SQL: {sql}")


def test_object_type_key_rejects_database_style_names():
    with pytest.raises(ValidationError):
        OntologyObjectTypePayload.model_validate(
            {
                "domain_id": 1,
                "object_key": "supplier-table",
                "name": "供应商",
                "primary_property": "supplier_id",
                "properties": [
                    {
                        "property_key": "supplier_id",
                        "name": "供应商编号",
                        "data_type": "string",
                    }
                ],
            }
        )


def test_normalize_row_preserves_nullable_json_values():
    assert _normalize_row({"default_value": None, "properties": None}) == {
        "default_value": None,
        "properties": {},
    }


def test_ontology_definition_hash_is_stable_across_mapping_order():
    first = {"domain": {"name": "贷款风控", "key": "loan"}, "objects": [1, 2]}
    second = {"objects": [1, 2], "domain": {"key": "loan", "name": "贷款风控"}}

    assert _content_hash(first) == _content_hash(second)


def test_release_definition_ignores_storage_and_sync_runtime_fields():
    base = {
        "format": "wenqu-ontology",
        "version": 1,
        "domain": {"domain_key": "loan", "name": "贷款风控"},
        "object_types": [
            {
                "id": 11,
                "domain_id": 4,
                "object_key": "Loan",
                "name": "贷款",
                "last_sync_count": 100,
                "properties": [
                    {
                        "id": 21,
                        "object_type_id": 11,
                        "property_key": "loan_id",
                        "name": "贷款ID",
                        "sort_order": 0,
                        "default_value": {"id": "business-id"},
                    }
                ],
            }
        ],
        "link_types": [],
        "action_types": [],
    }
    other = json.loads(json.dumps(base))
    other["object_types"][0].update(
        {"id": 99, "domain_id": 8, "last_sync_count": 999, "updated_at": "later"}
    )
    other["object_types"][0]["properties"][0].update(
        {"id": 88, "object_type_id": 99, "created_at": "later"}
    )

    first = _stable_release_definition(base)
    second = _stable_release_definition(other)

    assert first == second
    assert first["object_types"][0]["properties"][0]["default_value"]["id"] == (
        "business-id"
    )
    assert _content_hash(first) == _content_hash(second)


def test_numeric_primary_values_accept_string_api_input():
    definition = {"property_key": "id", "name": "编号", "data_type": "integer"}
    assert coerce_primary_value(definition, "0042") == 42
    with pytest.raises(ValueError, match="必须是整数"):
        coerce_primary_value(definition, "not-a-number")


def test_object_payload_rejects_empty_primary_value():
    with pytest.raises(ValidationError):
        OntologyObjectPayload.model_validate(
            {
                "domain_id": 1,
                "object_type_id": 2,
                "primary_value": "",
            }
        )


def test_validate_property_values_applies_defaults_and_rejects_unknown_fields():
    values = validate_property_values(
        PROPERTY_DEFINITIONS,
        {"material_id": "MAT-001", "available_qty": 18.5},
    )
    assert values == {
        "material_id": "MAT-001",
        "available_qty": 18.5,
        "allocation_status": "available",
    }

    with pytest.raises(ValueError, match="未定义属性"):
        validate_property_values(
            PROPERTY_DEFINITIONS,
            {"material_id": "MAT-001", "available_qty": 18, "etl_timestamp": "x"},
        )


def test_action_parameter_and_precondition_validation():
    definitions = [
        {
            "parameter_key": "new_status",
            "name": "目标状态",
            "data_type": "string",
            "required": True,
            "options": ["reserved", "reallocated"],
        }
    ]
    params = validate_action_parameters(definitions, {"new_status": "reallocated"})
    assert params == {"new_status": "reallocated"}
    check_preconditions(
        [{"property": "available_qty", "operator": "gte", "value": 0}],
        {"available_qty": 10},
        params,
    )
    with pytest.raises(ValueError, match="前置条件"):
        check_preconditions(
            [{"property": "available_qty", "operator": "gt", "value": 10}],
            {"available_qty": 10},
            params,
        )


@pytest.mark.asyncio
async def test_execute_action_updates_object_and_records_decision_lineage(monkeypatch):
    db = RecordingDB()
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: db)
    service = OntologyService()
    audit_calls = []

    async def fake_append_action_audit(_session, **kwargs):
        audit_calls.append(kwargs)
        return 88

    monkeypatch.setattr(service, "_append_action_audit", fake_append_action_audit)

    async def fake_action(domain_id, action_type_id):
        assert (domain_id, action_type_id) == (4, 9)
        return {
            "id": 9,
            "action_key": "reallocate_material",
            "name": "调整物料分配",
            "target_object_key": "Material",
            "status": "active",
            "allowed_roles": ["admin", "user"],
            "requires_approval": False,
            "parameters": [
                {
                    "parameter_key": "new_quantity",
                    "name": "调整后数量",
                    "data_type": "number",
                    "required": True,
                    "options": [],
                },
                {
                    "parameter_key": "new_status",
                    "name": "调拨状态",
                    "data_type": "string",
                    "required": True,
                    "options": ["reserved", "reallocated"],
                },
            ],
            "preconditions": [
                {"property": "available_qty", "operator": "gte", "value": 0}
            ],
            "effects": [
                {"property": "available_qty", "value": "$param.new_quantity"},
                {"property": "allocation_status", "value": "$param.new_status"},
            ],
        }

    async def fake_object(domain_id, object_id):
        return {
            "id": object_id,
            "domain_id": domain_id,
            "object_type_id": 2,
            "object_type_key": "Material",
            "display_name": "医用无纺布",
            "version": 3,
            "properties": {
                "material_id": "MAT-001",
                "available_qty": 1800,
                "allocation_status": "available",
            },
        }

    async def fake_object_type(domain_id, **kwargs):
        return {
            "id": kwargs["object_type_id"],
            "object_key": "Material",
            "display_property": None,
            "properties": PROPERTY_DEFINITIONS,
        }

    monkeypatch.setattr(service, "get_action_type", fake_action)
    monkeypatch.setattr(service, "get_object", fake_object)
    monkeypatch.setattr(service, "get_object_type", fake_object_type)

    result = await service.execute_action(
        4,
        9,
        OntologyActionExecutePayload(
            target_object_id=22,
            parameters={"new_quantity": 1200, "new_status": "reallocated"},
            decision_context={"reason": "供应商中断"},
        ),
        {"id": 7, "username": "operator", "role": "user"},
    )

    assert result["status"] == "succeeded"
    assert result["audit_event_id"] == 88
    assert result["after_state"]["properties"]["available_qty"] == 1200
    run_params = db.inserts[0][1]
    assert run_params["ontology_release_id"] == 3
    assert json.loads(run_params["decision_context"])["reason"] == "供应商中断"
    assert json.loads(run_params["decision_context"])["ontology_release"] == {
        "id": 3,
        "version": 2,
        "definition_hash": "abc123",
    }
    object_update = next(
        params for sql, params in db.queries if sql.startswith("UPDATE ontology_object")
    )
    assert json.loads(object_update["properties"])["allocation_status"] == "reallocated"
    assert any("status = 'succeeded'" in sql for sql, _ in db.queries)
    assert audit_calls[0]["release_id"] == 3
    assert audit_calls[0]["status"] == "succeeded"
    assert audit_calls[0]["payload"]["after_state"]["properties"]["available_qty"] == 1200


@pytest.mark.asyncio
async def test_execute_action_rolls_back_when_unified_audit_fails(monkeypatch):
    db = RecordingDB()
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: db)
    service = OntologyService()

    async def fake_action(_domain_id, _action_type_id):
        return {
            "action_key": "reserve_material",
            "target_object_key": "Material",
            "status": "active",
            "allowed_roles": ["user"],
            "requires_approval": False,
            "parameters": [],
            "preconditions": [],
            "effects": [{"property": "allocation_status", "value": "reserved"}],
        }

    async def fake_object(_domain_id, object_id):
        return {
            "id": object_id,
            "object_type_id": 2,
            "object_type_key": "Material",
            "display_name": "医用无纺布",
            "version": 3,
            "properties": {
                "material_id": "MAT-001",
                "available_qty": 1800,
                "allocation_status": "available",
            },
        }

    async def fake_object_type(_domain_id, **_kwargs):
        return {
            "primary_property": "material_id",
            "display_property": None,
            "properties": PROPERTY_DEFINITIONS,
        }

    async def fail_audit(_session, **_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "get_action_type", fake_action)
    monkeypatch.setattr(service, "get_object", fake_object)
    monkeypatch.setattr(service, "get_object_type", fake_object_type)
    monkeypatch.setattr(service, "_append_action_audit", fail_audit)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await service.execute_action(
            4,
            9,
            OntologyActionExecutePayload(target_object_id=22, expected_version=3),
            {"id": 7, "username": "operator", "role": "user"},
        )

    assert db.inserts == []
    assert not any(sql.startswith("UPDATE ontology_object") for sql, _ in db.queries)


@pytest.mark.asyncio
async def test_publish_is_blocked_by_validation_errors(monkeypatch):
    service = OntologyService()

    async def invalid(_domain_id):
        return {
            "valid": False,
            "errors": [{"asset": "Material", "message": "主属性不存在"}],
            "warnings": [],
            "counts": {},
        }

    monkeypatch.setattr(service, "validate_domain", invalid)
    result = await service.publish_domain(1, 2)
    assert result["published"] is False
    assert result["validation"]["errors"][0]["asset"] == "Material"


@pytest.mark.asyncio
async def test_upsert_object_is_idempotent_for_same_primary_value(monkeypatch):
    class ExistingObjectDB(RecordingDB):
        async def execute_query(self, sql: str, params: dict | None = None):
            self.queries.append((sql, params or {}))
            if "SELECT id FROM ontology_object WHERE domain_id" in sql:
                return [{"id": 11}]
            return []

    db = ExistingObjectDB()
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: db)
    service = OntologyService()

    async def fake_object_type(_domain_id, **_kwargs):
        return {
            "id": 2,
            "object_key": "Material",
            "primary_property": "material_id",
            "display_property": None,
            "properties": PROPERTY_DEFINITIONS,
        }

    monkeypatch.setattr(service, "get_object_type", fake_object_type)
    item_id = await service.upsert_object(
        OntologyObjectPayload(
            domain_id=4,
            object_type_id=2,
            primary_value="MAT-001",
            properties={"material_id": "MAT-001", "available_qty": 10},
        )
    )
    assert item_id == 11
    assert not db.inserts
    assert any("version = version + 1" in sql for sql, _ in db.queries)


@pytest.mark.asyncio
async def test_import_bundle_rejects_unknown_references_before_replace(monkeypatch):
    service = OntologyService()
    cleared = False

    async def fake_require(_domain_id):
        return {"id": 4}

    async def fake_list(_domain_id):
        return []

    async def fake_clear(_domain_id):
        nonlocal cleared
        cleared = True

    monkeypatch.setattr(service, "_require_domain", fake_require)
    monkeypatch.setattr(service, "list_object_types", fake_list)
    monkeypatch.setattr(service, "_clear_domain", fake_clear)

    with pytest.raises(ValueError, match="未定义对象类型"):
        await service.import_bundle(
            4,
            {
                "format": "wenqu-ontology",
                "version": 1,
                "object_types": [],
                "link_types": [
                    {
                        "link_key": "missing_link",
                        "name": "缺失关系",
                        "source_object_key": "MissingSource",
                        "target_object_key": "MissingTarget",
                    }
                ],
            },
            replace=True,
        )
    assert cleared is False


@pytest.mark.asyncio
async def test_replace_is_blocked_after_release_or_decision_history(monkeypatch):
    class HistoryDB(RecordingDB):
        async def execute_query(self, sql: str, params: dict | None = None):
            self.queries.append((sql, params or {}))
            if sql.startswith("SELECT (SELECT COUNT(*) FROM ontology_release"):
                return [
                    {
                        "releases": 1,
                        "action_runs": 0,
                        "risk_issues": 0,
                        "reports": 0,
                        "audit_events": 0,
                    }
                ]
            return []

    db = HistoryDB()
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: db)

    with pytest.raises(ValueError, match="不能替换 Ontology"):
        await OntologyService()._clear_domain(4)


@pytest.mark.asyncio
async def test_object_with_risk_lineage_cannot_be_deleted(monkeypatch):
    class ReferencedObjectDB(RecordingDB):
        async def execute_query(self, sql: str, params: dict | None = None):
            self.queries.append((sql, params or {}))
            if "AS risk_issues" in sql:
                return [{"risk_issues": 1, "action_runs": 0}]
            return []

    db = ReferencedObjectDB()
    service = OntologyService()
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: db)

    async def fake_object(_domain_id, object_id):
        return {"id": object_id}

    monkeypatch.setattr(service, "get_object", fake_object)

    with pytest.raises(ValueError, match="不能删除"):
        await service.delete_object(4, 22)


@pytest.mark.asyncio
async def test_execute_action_rejects_stale_expected_version(monkeypatch):
    db = RecordingDB()
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: db)
    service = OntologyService()

    async def fake_action(_domain_id, _action_type_id):
        return {
            "action_key": "reallocate_material",
            "target_object_key": "Material",
            "status": "active",
            "allowed_roles": ["user"],
            "requires_approval": False,
            "parameters": [],
            "preconditions": [],
            "effects": [],
        }

    async def fake_object(_domain_id, _object_id):
        return {
            "object_type_key": "Material",
            "object_type_id": 2,
            "version": 3,
            "properties": {},
        }

    monkeypatch.setattr(service, "get_action_type", fake_action)
    monkeypatch.setattr(service, "get_object", fake_object)
    with pytest.raises(ValueError, match="版本已变化"):
        await service.execute_action(
            4,
            9,
            OntologyActionExecutePayload(target_object_id=22, expected_version=2),
            {"id": 7, "role": "user"},
        )
    assert not db.inserts
