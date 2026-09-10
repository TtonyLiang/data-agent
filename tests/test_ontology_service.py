import copy
import json

import pytest
from pydantic import ValidationError

from app.models.ontology import (
    OntologyActionExecutePayload,
    OntologyLinkTypePayload,
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
from app.services.permission_service import ColumnPolicy, PermissionRuntimeContext

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


async def _active_domain(domain_id: int):
    return {"id": domain_id, "status": "active"}


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


@pytest.fixture(autouse=True)
def no_active_enterprise_model_release(monkeypatch):
    class NoActiveReleaseService:
        async def get_active_release(self, _domain_id):
            return None

    monkeypatch.setattr(
        ontology_service, "get_model_release_service", lambda: NoActiveReleaseService()
    )


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


@pytest.mark.parametrize(
    "property_keys",
    [[], [""], ["tenant_id", "tenant_id"], ["租户"]],
)
def test_link_type_rejects_empty_duplicate_or_non_ascii_compound_keys(property_keys):
    with pytest.raises(ValidationError):
        OntologyLinkTypePayload.model_validate(
            {
                "domain_id": 1,
                "link_key": "customer_has_application",
                "name": "客户申请贷款",
                "source_object_key": "Customer",
                "target_object_key": "LoanApplication",
                "source_property_keys": property_keys,
                "target_property_keys": ["tenant_id"],
            }
        )


def test_link_type_rejects_conflicting_single_and_compound_aliases():
    with pytest.raises(ValidationError, match="单属性键必须与复合属性键首项一致"):
        OntologyLinkTypePayload.model_validate(
            {
                "domain_id": 1,
                "link_key": "customer_has_application",
                "name": "客户申请贷款",
                "source_object_key": "Customer",
                "target_object_key": "LoanApplication",
                "source_property": "customer_id",
                "source_property_keys": ["tenant_id", "customer_id"],
                "target_property_keys": ["tenant_id", "customer_id"],
            }
        )


@pytest.mark.asyncio
async def test_link_type_persists_and_reads_compound_property_keys(monkeypatch):
    class CompositeLinkDB(RecordingDB):
        def __init__(self):
            super().__init__()
            self.link_row = None

        async def execute_query(self, sql: str, params: dict | None = None):
            self.queries.append((sql, params or {}))
            if sql.startswith("SELECT * FROM ontology_link_type"):
                return [copy.deepcopy(self.link_row)] if self.link_row else []
            return []

        async def execute_insert(self, sql: str, params: dict | None = None):
            self.inserts.append((sql, params or {}))
            self.link_row = {"id": 77, **(params or {})}
            return 77

    db = CompositeLinkDB()
    service = OntologyService()
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: db)
    monkeypatch.setattr(service, "_require_domain", _active_domain)

    async def fake_object_type(_domain_id, *, object_key=None, **_kwargs):
        return {
            "object_key": object_key,
            "primary_property": "customer_id" if object_key == "Customer" else "application_id",
            "properties": [
                {"property_key": "tenant_id"},
                {"property_key": "customer_id"},
                {"property_key": "application_id"},
            ],
        }

    monkeypatch.setattr(service, "get_object_type", fake_object_type)
    link_id = await service.upsert_link_type(
        OntologyLinkTypePayload(
            domain_id=4,
            link_key="customer_has_application",
            name="客户申请贷款",
            source_object_key="Customer",
            target_object_key="LoanApplication",
            source_property_keys=["tenant_id", "customer_id"],
            target_property_keys=["tenant_id", "customer_id"],
        )
    )

    assert link_id == 77
    assert db.inserts[0][1]["source_property"] == "tenant_id,customer_id"
    assert db.inserts[0][1]["target_property"] == "tenant_id,customer_id"
    links = await service.list_link_types(4)
    assert links[0]["source_property"] == "tenant_id"
    assert links[0]["target_property"] == "tenant_id"
    assert links[0]["source_property_keys"] == ["tenant_id", "customer_id"]
    assert links[0]["target_property_keys"] == ["tenant_id", "customer_id"]


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
    assert first["object_types"][0]["properties"][0]["default_value"]["id"] == ("business-id")
    assert _content_hash(first) == _content_hash(second)


def test_release_definition_normalizes_legacy_and_runtime_relation_keys():
    legacy = {
        "format": "wenqu-ontology",
        "version": 1,
        "domain": {"domain_key": "loan"},
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
    runtime = copy.deepcopy(legacy)
    runtime["link_types"][0].update(
        {
            "source_property": "tenant_id",
            "target_property": "tenant_id",
            "source_property_keys": ["tenant_id", "customer_id"],
            "target_property_keys": ["tenant_id", "customer_id"],
        }
    )

    assert _stable_release_definition(legacy) == _stable_release_definition(runtime)
    legacy_hash = _content_hash(_stable_release_definition(legacy))
    runtime_hash = _content_hash(_stable_release_definition(runtime))
    assert legacy_hash == runtime_hash


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
    monkeypatch.setattr(service, "_require_domain", _active_domain)
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
            "preconditions": [{"property": "available_qty", "operator": "gte", "value": 0}],
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
    assert result["state_commit"] == {
        "mode": "platform_object",
        "business_source_written": False,
        "message": "动作已更新平台本地对象；当前没有外部业务系统写回",
    }
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
    assert result["warnings"][0]["code"] == "enterprise_model_release_fallback"


@pytest.mark.asyncio
async def test_build_agent_context_uses_active_model_release_definition(monkeypatch):
    definition = {
        "domain": {
            "domain_key": "loan",
            "name": "已发布贷款领域",
            "description": "来自不可变发布定义",
        },
        "object_types": [
            {
                "object_key": "LoanApplication",
                "name": "已发布贷款申请",
                "description": "发布版本对象",
                "primary_property": "application_id",
                "display_property": "application_id",
                "status": "active",
                "properties": [
                    {
                        "property_key": "application_id",
                        "name": "申请编号",
                        "data_type": "string",
                        "required": True,
                    }
                ],
            }
        ],
        "link_types": [],
        "action_types": [],
    }
    definition_hash = ontology_service._content_hash(definition)
    semantic_hash = "b" * 64
    model_hash = ontology_service._content_hash(
        {
            "format": "wenqu-enterprise-model-release/v1",
            "semantic_snapshot_hash": semantic_hash,
            "ontology_definition_hash": definition_hash,
        }
    )

    class ActiveReleaseService:
        async def get_active_release(self, domain_id):
            assert domain_id == 4
            return {
                "id": 20,
                "version": 3,
                "name": "企业模型 V3",
                "status": "active",
                "model_hash": model_hash,
                "semantic_snapshot_id": 12,
                "semantic_snapshot_hash": semantic_hash,
                "ontology_release_id": 13,
                "ontology_definition_hash": definition_hash,
                "activated_at": "2026-09-07T10:00:00",
            }

    class ReleasedDefinitionDB:
        async def execute_query(self, sql, params=None):
            assert "WHERE id = :release_id AND domain_id = :domain_id" in sql
            assert params == {"release_id": 13, "domain_id": 4}
            return [
                {
                    "id": 13,
                    "domain_id": 4,
                    "version": 7,
                    "name": "Ontology V7",
                    "description": "fixed",
                    "definition_json": json.dumps(definition, ensure_ascii=False),
                    "definition_hash": definition_hash,
                    "created_at": "2026-09-07T09:00:00",
                }
            ]

    service = OntologyService()

    async def fake_require(_domain_id):
        return {
            "id": 4,
            "domain_key": "live_domain",
            "name": "实时领域",
            "description": "不应进入发布上下文",
        }

    async def must_not_load_live(_domain_id):
        raise AssertionError("active model release must not read live definitions")

    monkeypatch.setattr(
        ontology_service, "get_model_release_service", lambda: ActiveReleaseService()
    )
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: ReleasedDefinitionDB())
    monkeypatch.setattr(service, "_require_domain", fake_require)
    monkeypatch.setattr(service, "list_object_types", must_not_load_live)
    monkeypatch.setattr(service, "list_link_types", must_not_load_live)
    monkeypatch.setattr(service, "list_action_types", must_not_load_live)

    context = await service.build_agent_context(4, role="user")

    assert context["domain"]["name"] == "已发布贷款领域"
    assert context["object_types"][0]["name"] == "已发布贷款申请"
    assert context["model_release"]["id"] == 20
    assert context["semantic_snapshot"] == {
        "id": 12,
        "snapshot_hash": semantic_hash,
    }
    assert context["ontology_release"]["id"] == 13
    assert context["release"] == context["ontology_release"]
    assert context["warnings"] == []


@pytest.mark.asyncio
async def test_build_agent_context_rejects_tampered_active_release_definition(monkeypatch):
    definition = {
        "domain": {"domain_key": "loan", "name": "贷款领域"},
        "object_types": [],
        "link_types": [],
        "action_types": [],
    }

    class ActiveReleaseService:
        async def get_active_release(self, _domain_id):
            return {
                "id": 20,
                "version": 3,
                "name": "企业模型 V3",
                "status": "active",
                "model_hash": "c" * 64,
                "semantic_snapshot_id": 12,
                "semantic_snapshot_hash": "b" * 64,
                "ontology_release_id": 13,
                "ontology_definition_hash": "a" * 64,
                "activated_at": "2026-09-07T10:00:00",
            }

    class TamperedDefinitionDB:
        async def execute_query(self, _sql, _params=None):
            return [
                {
                    "id": 13,
                    "domain_id": 4,
                    "version": 7,
                    "name": "Ontology V7",
                    "description": "tampered",
                    "definition_json": json.dumps(definition, ensure_ascii=False),
                    "definition_hash": "a" * 64,
                    "created_at": "2026-09-07T09:00:00",
                }
            ]

    service = OntologyService()
    monkeypatch.setattr(
        ontology_service, "get_model_release_service", lambda: ActiveReleaseService()
    )
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: TamperedDefinitionDB())

    with pytest.raises(ValueError, match="完整性校验失败"):
        await service._load_runtime_definition(4)


@pytest.mark.asyncio
async def test_execute_action_uses_definition_bound_to_active_model_release(monkeypatch):
    db = RecordingDB()
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: db)
    service = OntologyService()
    monkeypatch.setattr(service, "_require_domain", _active_domain)

    async def fake_action(_domain_id, _action_type_id):
        return {
            "id": 9,
            "action_key": "reserve_material",
            "target_object_key": "Material",
            "status": "active",
            "allowed_roles": ["user"],
            "requires_approval": False,
            "parameters": [],
            "preconditions": [],
            "effects": [{"property": "allocation_status", "value": "live_value"}],
        }

    async def fake_runtime_definition(_domain_id):
        return (
            {
                "id": 20,
                "version": 3,
                "name": "企业模型 V3",
                "status": "active",
                "model_hash": "c" * 64,
                "activated_at": "2026-09-07T10:00:00",
            },
            {"id": 12, "snapshot_hash": "b" * 64},
            {"id": 13, "version": 7, "definition_hash": "a" * 64},
            {
                "object_types": [
                    {
                        "object_key": "Material",
                        "primary_property": "material_id",
                        "display_property": None,
                        "status": "active",
                        "properties": PROPERTY_DEFINITIONS,
                    }
                ],
                "action_types": [
                    {
                        "action_key": "reserve_material",
                        "target_object_key": "Material",
                        "status": "active",
                        "allowed_roles": ["user"],
                        "requires_approval": False,
                        "parameters": [],
                        "preconditions": [],
                        "effects": [{"property": "allocation_status", "value": "released_value"}],
                    }
                ],
            },
            [],
        )

    async def fake_object(_domain_id, object_id):
        return {
            "id": object_id,
            "object_type_id": 2,
            "object_type_key": "Material",
            "display_name": "医用无纺布",
            "version": 1,
            "properties": {
                "material_id": "MAT-001",
                "available_qty": 10,
                "allocation_status": "available",
            },
        }

    async def fake_audit(_session, **_kwargs):
        return 88

    monkeypatch.setattr(service, "get_action_type", fake_action)
    monkeypatch.setattr(service, "_load_runtime_definition", fake_runtime_definition)
    monkeypatch.setattr(service, "get_object", fake_object)
    monkeypatch.setattr(service, "_append_action_audit", fake_audit)

    result = await service.execute_action(
        4,
        9,
        OntologyActionExecutePayload(target_object_id=22),
        {"id": 7, "username": "operator", "role": "user"},
    )

    run_params = db.inserts[0][1]
    object_update = next(
        params for sql, params in db.queries if sql.startswith("UPDATE ontology_object")
    )
    assert run_params["ontology_release_id"] == 13
    assert json.loads(object_update["properties"])["allocation_status"] == "released_value"
    assert result["model_release"]["id"] == 20
    assert result["semantic_snapshot"]["id"] == 12
    assert result["ontology_release"]["id"] == 13
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_execute_action_rolls_back_when_unified_audit_fails(monkeypatch):
    db = RecordingDB()
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: db)
    service = OntologyService()
    monkeypatch.setattr(service, "_require_domain", _active_domain)

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
async def test_upsert_object_rejects_primary_identity_change(monkeypatch):
    db = RecordingDB()
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

    async def fake_object(_domain_id, _object_id):
        return {
            "id": 11,
            "object_type_id": 2,
            "primary_value": "MAT-001",
            "source_kind": "database",
            "source_properties": {
                "material_id": "MAT-001",
                "available_qty": 10,
                "allocation_status": "available",
            },
            "overlay_properties": {},
        }

    monkeypatch.setattr(service, "get_object_type", fake_object_type)
    monkeypatch.setattr(service, "get_object", fake_object)

    with pytest.raises(ValueError, match="对象主标识不可修改"):
        await service.upsert_object(
            OntologyObjectPayload(
                id=11,
                domain_id=4,
                object_type_id=2,
                primary_value="MAT-002",
                properties={
                    "material_id": "MAT-002",
                    "available_qty": 10,
                    "allocation_status": "available",
                },
            )
        )

    assert not any(sql.startswith("UPDATE ontology_object") for sql, _ in db.queries)


@pytest.mark.asyncio
async def test_upsert_object_normalizes_numeric_identity_and_never_overlays_primary(monkeypatch):
    db = RecordingDB()
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: db)
    service = OntologyService()
    definitions = [
        {
            "property_key": "entity_id",
            "name": "实体编号",
            "data_type": "number",
            "required": True,
            "default_value": None,
        },
        {
            "property_key": "name",
            "name": "名称",
            "data_type": "string",
            "required": True,
            "default_value": None,
        },
    ]

    async def fake_object_type(_domain_id, **_kwargs):
        return {
            "id": 2,
            "object_key": "Entity",
            "primary_property": "entity_id",
            "display_property": "name",
            "properties": definitions,
        }

    async def fake_object(_domain_id, _object_id):
        return {
            "id": 11,
            "object_type_id": 2,
            "primary_value": "1.0",
            "source_kind": "database",
            "source_properties": {"entity_id": 1.0, "name": "原名称"},
            "overlay_properties": {},
        }

    monkeypatch.setattr(service, "get_object_type", fake_object_type)
    monkeypatch.setattr(service, "get_object", fake_object)

    item_id = await service.upsert_object(
        OntologyObjectPayload(
            id=11,
            domain_id=4,
            object_type_id=2,
            primary_value=1,
            properties={"entity_id": 1, "name": "新名称"},
        )
    )

    update = next(params for sql, params in db.queries if sql.startswith("UPDATE ontology_object"))
    assert item_id == 11
    assert json.loads(update["overlay_properties"]) == {"name": "新名称"}
    assert json.loads(update["properties"])["entity_id"] == 1.0


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
    monkeypatch.setattr(service, "_require_domain", _active_domain)

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


@pytest.mark.asyncio
async def test_object_query_and_list_apply_column_visibility_and_masking(monkeypatch):
    source_query = (
        "SELECT application_id, mobile, id_card "
        "FROM loan_application_indicator ORDER BY application_id"
    )
    object_row = {
        "id": 101,
        "domain_id": 4,
        "object_type_id": 11,
        "object_type_key": "LoanApplication",
        "object_type_name": "贷款申请",
        "primary_value": "APP-001",
        "display_name": "13800138000",
        "properties": {
            "application_id": "APP-001",
            "mobile": "13800138000",
            "id_card": "110101199001011234",
        },
        "source_properties": {
            "application_id": "APP-001",
            "mobile": "13800138000",
            "id_card": "110101199001011234",
        },
        "overlay_properties": {"id_card": "updated"},
        "source_kind": "database",
        "source_datasource_id": 42,
        "status": "active",
        "_permission_source_query": source_query,
        "_permission_primary_property": "application_id",
        "_permission_display_property": "mobile",
    }

    class ObjectDB:
        async def execute_query(self, sql: str, params: dict | None = None):
            if sql.startswith("SELECT id, source_query, primary_property"):
                return [
                    {
                        "id": 11,
                        "source_query": source_query,
                        "primary_property": "application_id",
                    }
                ]
            if sql.startswith("SELECT COUNT(*) AS count FROM ontology_object"):
                return [{"count": 1}]
            if sql.startswith("SELECT o.*"):
                return [copy.deepcopy(object_row)]
            raise AssertionError(f"unexpected query: {sql}")

    class ObjectPermissionService:
        async def get_table_permissions(self, agent_id, datasource_id):
            assert (agent_id, datasource_id) == (7, 42)
            return {"loan_application_indicator": True}

        async def get_column_permissions(self, agent_id, datasource_id):
            assert (agent_id, datasource_id) == (7, 42)
            return {
                ("loan_application_indicator", "mobile"): ColumnPolicy(
                    allowed=True, masking_policy="partial"
                ),
                ("loan_application_indicator", "id_card"): ColumnPolicy(
                    allowed=False, masking_policy="redact"
                ),
            }

        @staticmethod
        def table_allowed(table_name, table_permissions):
            return bool(table_permissions.get(table_name.lower(), False))

    class ObjectDatasourceService:
        async def belongs_to_agent(self, datasource_id, agent_id):
            return (datasource_id, agent_id) == (42, 7)

    service = OntologyService()

    async def require_domain(_domain_id: int):
        return {"id": 4, "agent_id": None, "datasource_id": 42}

    monkeypatch.setattr(service, "_require_domain", require_domain)
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: ObjectDB())
    monkeypatch.setattr(
        ontology_service,
        "get_permission_service",
        lambda: ObjectPermissionService(),
    )
    monkeypatch.setattr(
        ontology_service,
        "get_datasource_service",
        lambda: ObjectDatasourceService(),
    )

    queried = await service.query_objects(4, access_agent_id=7)
    listed = await service.list_objects(4, access_agent_id=7)

    for item in [queried["objects"][0], listed[0]]:
        assert item["display_name"] == "13*******00"
        assert item["properties"]["mobile"] == "13*******00"
        assert "id_card" not in item["properties"]
        assert "id_card" not in item["source_properties"]
        assert "id_card" not in item["overlay_properties"]
        assert not any(key.startswith("_permission_") for key in item)


@pytest.mark.asyncio
async def test_unconfigured_domain_permissions_show_manual_objects_only(monkeypatch):
    manual_row = {
        "id": 201,
        "domain_id": 4,
        "object_type_id": 11,
        "object_type_key": "Student",
        "object_type_name": "学生",
        "primary_value": "S-001",
        "display_name": "学生一",
        "properties": {"student_id": "S-001", "name": "学生一"},
        "source_properties": {},
        "overlay_properties": {},
        "source_kind": "manual",
        "source_datasource_id": None,
        "status": "active",
        "_permission_source_query": "",
        "_permission_primary_property": "student_id",
        "_permission_display_property": "name",
    }

    class ManualOnlyDB:
        async def execute_query(self, sql, params=None):
            if sql.startswith("SELECT id, source_query, primary_property"):
                return [
                    {
                        "id": 12,
                        "source_query": (
                            "SELECT application_id FROM loan_application "
                            "ORDER BY application_id"
                        ),
                        "primary_property": "application_id",
                    }
                ]
            if sql.startswith("SELECT COUNT(*) AS count"):
                assert "o.source_kind <> 'database'" in sql
                return [{"count": 1}]
            if sql.startswith("SELECT o.*"):
                assert "o.source_kind <> 'database'" in sql
                return [copy.deepcopy(manual_row)]
            raise AssertionError(sql)

    class UnconfiguredPermissionService:
        async def resolve_domain_permission_context(self, domain_id, datasource_id, **_kwargs):
            return PermissionRuntimeContext(
                domain_id=domain_id,
                datasource_id=datasource_id,
                source="unconfigured",
                table_permissions={},
                column_permissions={},
            )

        @staticmethod
        def table_allowed(_table_name, _table_permissions):
            return False

    service = OntologyService()

    async def require_domain(_domain_id):
        return {"id": 4, "datasource_id": 42}

    monkeypatch.setattr(service, "_require_domain", require_domain)
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: ManualOnlyDB())
    monkeypatch.setattr(
        ontology_service,
        "get_permission_service",
        lambda: UnconfiguredPermissionService(),
    )

    result = await service.query_objects(4)

    assert result["total"] == 1
    assert result["objects"][0]["display_name"] == "学生一"
    assert result["permission"]["source"] == "unconfigured"


def test_object_protection_masks_aliased_source_property():
    rows = [
        {
            "id": 101,
            "primary_value": "C-001",
            "display_name": "13800138000",
            "properties": {
                "customer_id": "C-001",
                "contact_phone": "13800138000",
            },
            "source_properties": {},
            "overlay_properties": {},
            "source_kind": "database",
            "source_datasource_id": 42,
            "_permission_source_query": (
                "SELECT customer_id, phone_number AS contact_phone "
                "FROM customer_indicator ORDER BY customer_id"
            ),
            "_permission_primary_property": "customer_id",
            "_permission_display_property": "contact_phone",
        }
    ]
    permission_context = (
        42,
        {"customer_indicator": True},
        {
            ("customer_indicator", "phone_number"): ColumnPolicy(
                allowed=True,
                masking_policy="partial",
            )
        },
    )

    protected = OntologyService._protect_object_rows(rows, permission_context)

    assert protected[0]["display_name"] == "13*******00"
    assert protected[0]["properties"]["contact_phone"] == "13*******00"


@pytest.mark.asyncio
async def test_object_query_excludes_masked_primary_type_from_rows_and_total(monkeypatch):
    source_query = (
        "SELECT application_id, mobile FROM loan_application_indicator ORDER BY application_id"
    )

    class HiddenPrimaryDB:
        async def execute_query(self, sql, params=None):
            if sql.startswith("SELECT id, source_query, primary_property"):
                return [
                    {
                        "id": 11,
                        "source_query": source_query,
                        "primary_property": "application_id",
                    }
                ]
            if sql.startswith("SELECT COUNT(*) AS count"):
                assert "o.source_kind <> 'database'" in sql
                return [{"count": 0}]
            if sql.startswith("SELECT o.*"):
                assert "o.source_kind <> 'database'" in sql
                return []
            raise AssertionError(f"unexpected query: {sql}")

    class HiddenPrimaryPermission:
        async def get_table_permissions(self, agent_id, datasource_id):
            return {"loan_application_indicator": True}

        async def get_column_permissions(self, agent_id, datasource_id):
            return {
                ("loan_application_indicator", "application_id"): ColumnPolicy(
                    allowed=True, masking_policy="hash"
                )
            }

        @staticmethod
        def table_allowed(table_name, table_permissions):
            return bool(table_permissions.get(table_name.lower(), False))

    class BoundDatasourceService:
        async def belongs_to_agent(self, datasource_id, agent_id):
            return (datasource_id, agent_id) == (42, 7)

    service = OntologyService()

    async def require_domain(_domain_id):
        return {"id": 4, "datasource_id": 42}

    monkeypatch.setattr(service, "_require_domain", require_domain)
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: HiddenPrimaryDB())
    monkeypatch.setattr(
        ontology_service,
        "get_permission_service",
        lambda: HiddenPrimaryPermission(),
    )
    monkeypatch.setattr(
        ontology_service,
        "get_datasource_service",
        lambda: BoundDatasourceService(),
    )

    result = await service.query_objects(4, access_agent_id=7)

    assert result["objects"] == []
    assert result["total"] == 0
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_list_links_masks_visible_endpoint_names_and_hides_forbidden_endpoints(
    monkeypatch,
):
    allowed_source = (
        "SELECT customer_id, customer_name FROM customer_indicator ORDER BY customer_id"
    )
    allowed_target = (
        "SELECT application_id, application_no "
        "FROM loan_application_indicator ORDER BY application_id"
    )
    forbidden_source = "SELECT secret_id, secret_name FROM secret_customer ORDER BY secret_id"
    base_row = {
        "id": 70,
        "domain_id": 4,
        "link_type_id": 31,
        "source_object_id": 101,
        "target_object_id": 201,
        "properties": {},
        "link_key": "customer_has_application",
        "link_type_name": "客户申请贷款",
        "source_name": "张三客户",
        "source_primary_value": "C-001",
        "target_name": "APP-2026-001",
        "target_primary_value": "A-001",
        "_permission_source_source_kind": "database",
        "_permission_source_datasource_id": 42,
        "_permission_source_source_query": allowed_source,
        "_permission_source_primary_property": "customer_id",
        "_permission_source_display_property": "customer_name",
        "_permission_target_source_kind": "database",
        "_permission_target_datasource_id": 42,
        "_permission_target_source_query": allowed_target,
        "_permission_target_primary_property": "application_id",
        "_permission_target_display_property": "application_no",
    }
    hidden_row = {
        **base_row,
        "id": 71,
        "source_object_id": 102,
        "source_name": "禁止泄漏的客户",
        "source_primary_value": "SECRET-001",
        "_permission_source_source_query": forbidden_source,
        "_permission_source_primary_property": "secret_id",
        "_permission_source_display_property": "secret_name",
    }

    class LinkDB:
        async def execute_query(self, sql, params=None):
            assert "FROM ontology_link" in sql
            return [copy.deepcopy(base_row), copy.deepcopy(hidden_row)]

    class LinkPermissionService:
        async def get_table_permissions(self, agent_id, datasource_id):
            assert (agent_id, datasource_id) == (7, 42)
            return {
                "customer_indicator": True,
                "loan_application_indicator": True,
                "secret_customer": False,
            }

        async def get_column_permissions(self, agent_id, datasource_id):
            return {
                ("customer_indicator", "customer_name"): ColumnPolicy(
                    allowed=True, masking_policy="partial"
                ),
                ("loan_application_indicator", "application_no"): ColumnPolicy(
                    allowed=True, masking_policy="partial"
                ),
            }

        @staticmethod
        def table_allowed(table_name, table_permissions):
            return bool(table_permissions.get(table_name.lower(), False))

    class LinkDatasourceService:
        async def belongs_to_agent(self, datasource_id, agent_id):
            return (datasource_id, agent_id) == (42, 7)

    service = OntologyService()

    async def require_domain(_domain_id):
        return {"id": 4, "datasource_id": 42}

    monkeypatch.setattr(service, "_require_domain", require_domain)
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: LinkDB())
    monkeypatch.setattr(ontology_service, "get_permission_service", lambda: LinkPermissionService())
    monkeypatch.setattr(ontology_service, "get_datasource_service", lambda: LinkDatasourceService())

    links = await service.list_links(4, access_agent_id=7)

    assert len(links) == 1
    assert links[0]["source_name"] == "****"
    assert links[0]["target_name"] == "AP********01"
    assert links[0]["source_primary_value"] == "C-001"
    assert links[0]["target_primary_value"] == "A-001"
    assert "禁止泄漏的客户" not in str(links)
    assert "SECRET-001" not in str(links)
    assert not any(key.startswith("_permission_") for key in links[0])


@pytest.mark.asyncio
async def test_execute_action_rejects_database_object_hidden_by_table_permission(monkeypatch):
    db = RecordingDB()
    service = OntologyService()

    async def fake_action(_domain_id, _action_type_id):
        return {
            "action_key": "approve_application",
            "target_object_key": "LoanApplication",
            "status": "active",
            "allowed_roles": ["user"],
            "requires_approval": False,
            "parameters": [],
            "preconditions": [],
            "effects": [{"property": "status", "value": "approved"}],
        }

    async def fake_runtime_definition(_domain_id):
        return None, None, {"id": 3, "version": 1}, None, []

    async def fake_object(_domain_id, object_id):
        return {
            "id": object_id,
            "domain_id": 4,
            "object_type_id": 11,
            "object_type_key": "LoanApplication",
            "primary_value": "APP-001",
            "display_name": "APP-001",
            "properties": {"application_id": "APP-001", "status": "pending"},
            "source_properties": {"application_id": "APP-001", "status": "pending"},
            "overlay_properties": {},
            "source_kind": "database",
            "source_datasource_id": 42,
            "version": 1,
        }

    async def fake_object_type(_domain_id, **_kwargs):
        return {
            "object_key": "LoanApplication",
            "primary_property": "application_id",
            "display_property": "application_id",
            "source_query": (
                "SELECT application_id, status "
                "FROM loan_application_indicator ORDER BY application_id"
            ),
            "properties": [
                {
                    "property_key": "application_id",
                    "name": "申请编号",
                    "data_type": "string",
                    "required": True,
                },
                {
                    "property_key": "status",
                    "name": "状态",
                    "data_type": "string",
                    "required": True,
                },
            ],
        }

    class HiddenPermissionService:
        async def get_table_permissions(self, agent_id, datasource_id):
            return {"loan_application_indicator": False}

        async def get_column_permissions(self, agent_id, datasource_id):
            return {}

        @staticmethod
        def table_allowed(table_name, table_permissions):
            return bool(table_permissions.get(table_name.lower(), False))

    class BoundDatasourceService:
        async def belongs_to_agent(self, datasource_id, agent_id):
            return (datasource_id, agent_id) == (42, 7)

    async def require_domain(_domain_id):
        return {"id": 4, "datasource_id": 42}

    monkeypatch.setattr(ontology_service, "get_management_db", lambda: db)
    monkeypatch.setattr(service, "get_action_type", fake_action)
    monkeypatch.setattr(service, "_load_runtime_definition", fake_runtime_definition)
    monkeypatch.setattr(service, "get_object", fake_object)
    monkeypatch.setattr(service, "get_object_type", fake_object_type)
    monkeypatch.setattr(service, "_require_domain", require_domain)
    monkeypatch.setattr(
        ontology_service, "get_permission_service", lambda: HiddenPermissionService()
    )
    monkeypatch.setattr(
        ontology_service, "get_datasource_service", lambda: BoundDatasourceService()
    )

    with pytest.raises(PermissionError, match="无权访问目标对象"):
        await service.execute_action(
            4,
            9,
            OntologyActionExecutePayload(target_object_id=22),
            {"id": 7, "username": "operator", "role": "user"},
            access_agent_id=7,
        )

    assert db.inserts == []


@pytest.mark.asyncio
async def test_action_runs_mask_target_and_state_with_explicit_permission_subject(
    monkeypatch,
):
    source_query = (
        "SELECT application_id, application_no, status "
        "FROM loan_application_indicator ORDER BY application_id"
    )
    action_run = {
        "id": 81,
        "domain_id": 4,
        "target_object_id": 22,
        "target_name": "APP-2026-001",
        "action_key": "approve_application",
        "action_name": "审批通过",
        "before_state": {"properties": {"application_id": "A-1", "status": "pending"}},
        "after_state": {"properties": {"application_id": "A-1", "status": "approved"}},
        "_permission_target_primary_value": "A-1",
        "_permission_target_source_kind": "database",
        "_permission_target_datasource_id": 42,
        "_permission_target_source_query": source_query,
        "_permission_target_primary_property": "application_id",
        "_permission_target_display_property": "application_no",
    }

    class ActionRunDB:
        async def execute_query(self, sql, params=None):
            assert "FROM ontology_action_run" in sql
            return [copy.deepcopy(action_run)]

    class ActionRunPermission:
        async def get_table_permissions(self, agent_id, datasource_id):
            return {"loan_application_indicator": True}

        async def get_column_permissions(self, agent_id, datasource_id):
            return {
                ("loan_application_indicator", "application_no"): ColumnPolicy(
                    allowed=True, masking_policy="partial"
                ),
                ("loan_application_indicator", "status"): ColumnPolicy(
                    allowed=True, masking_policy="redact"
                ),
            }

        @staticmethod
        def table_allowed(table_name, table_permissions):
            return bool(table_permissions.get(table_name.lower(), False))

    class BoundDatasourceService:
        async def belongs_to_agent(self, datasource_id, agent_id):
            return (datasource_id, agent_id) == (42, 7)

    service = OntologyService()

    async def require_domain(_domain_id):
        return {"id": 4, "datasource_id": 42}

    monkeypatch.setattr(service, "_require_domain", require_domain)
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: ActionRunDB())
    monkeypatch.setattr(ontology_service, "get_permission_service", lambda: ActionRunPermission())
    monkeypatch.setattr(
        ontology_service,
        "get_datasource_service",
        lambda: BoundDatasourceService(),
    )

    runs = await service.list_action_runs(4, access_agent_id=7)

    assert runs[0]["target_name"] == "AP********01"
    assert runs[0]["before_state"]["properties"]["status"] == "***"
    assert runs[0]["after_state"]["properties"]["status"] == "***"
    assert "pending" not in str(runs)
    assert "approved" not in str(runs)
