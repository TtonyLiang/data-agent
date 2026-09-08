import json

import pytest

from app.db.model_release_schema import MODEL_RELEASE_TABLE_STATEMENTS
from app.models.model_release import (
    EnterpriseModelReleaseCreatePayload,
    EnterpriseModelValidationPayload,
)
from app.services import model_release_service
from app.services.decision_audit_service import canonical_sha256
from app.services.model_release_service import (
    ModelReleaseConflict,
    ModelReleaseService,
    _validate_component_payloads,
)


def _semantic_snapshot(metric_key: str, object_key: str, base_table: str) -> dict:
    return {
        "version": 1,
        "domain": {
            "id": 9,
            "domain_key": "loan_risk",
            "name": "贷款风控",
            "status": "active",
        },
        "assets": {
            "concept": [],
            "relation": [],
            "metric": [
                {
                    "domain_id": 9,
                    "metric_key": metric_key,
                    "name": metric_key,
                    "formula_sql": "COUNT(*)",
                    "base_table": base_table,
                    "metadata": {"object_key": object_key},
                }
            ],
            "rule": [],
            "mapping": [],
            "template": [],
        },
    }


def _ontology_definition(object_key: str) -> dict:
    return {
        "format": "wenqu-ontology",
        "version": 1,
        "domain": {
            "domain_key": "loan_risk",
            "name": "贷款风控",
        },
        "object_types": [
            {
                "object_key": object_key,
                "name": object_key,
                "primary_property": "record_id",
                "display_property": "record_id",
                "status": "active",
                "properties": [
                    {
                        "property_key": "record_id",
                        "name": "记录ID",
                        "data_type": "integer",
                        "required": True,
                        "unique": True,
                    }
                ],
            }
        ],
        "link_types": [],
        "action_types": [],
    }


def _relation_components(
    *,
    relation_key: str | None = "customer_submits_application",
    source: str = "Customer",
    target: str = "LoanApplication",
) -> tuple[dict, dict]:
    snapshot = _semantic_snapshot(
        "application_count", "LoanApplication", "loan_application"
    )
    if relation_key is not None:
        snapshot["assets"]["relation"] = [
            {
                "domain_id": 9,
                "relation_key": relation_key,
                "relation_type": "join_path",
                "source_concept": source,
                "target_concept": target,
                "name": "客户提交申请查询路径",
                "join_path": [
                    {
                        "left": "customer.customer_id",
                        "right": "loan_application.customer_id",
                    }
                ],
            }
        ]
    definition = _ontology_definition("Customer")
    definition["object_types"].append(
        _ontology_definition("LoanApplication")["object_types"][0]
    )
    definition["link_types"] = [
        {
            "link_key": "customer_submits_application",
            "name": "客户提交申请",
            "source_object_key": "Customer",
            "target_object_key": "LoanApplication",
            "source_property": "record_id",
            "target_property": "record_id",
            "status": "active",
        }
    ]
    return snapshot, definition


class FakeResult:
    def __init__(self, rows=None, *, lastrowid=0, rowcount=0):
        self.rows = rows or []
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class ModelReleaseDB:
    def __init__(self):
        application_definition = _ontology_definition("LoanApplication")
        account_definition = _ontology_definition("LoanAccount")
        self.domains = {9}
        self.snapshots = {
            10: {
                "id": 10,
                "domain_id": 9,
                "snapshot_json": _semantic_snapshot(
                    "application_count", "LoanApplication", "loan_application"
                ),
            },
            11: {
                "id": 11,
                "domain_id": 9,
                "snapshot_json": _semantic_snapshot(
                    "account_count", "LoanAccount", "loan_account"
                ),
            },
            12: {"id": 12, "domain_id": 99, "snapshot_json": {"metrics": []}},
        }
        self.ontology_releases = {
            20: {
                "id": 20,
                "domain_id": 9,
                "definition_json": application_definition,
                "definition_hash": canonical_sha256(application_definition),
            },
            21: {
                "id": 21,
                "domain_id": 9,
                "definition_json": account_definition,
                "definition_hash": canonical_sha256(account_definition),
            },
        }
        self.releases: dict[int, dict] = {}
        self.next_id = 100

    async def execute_in_transaction(self, callback):
        return await callback(self)

    async def execute_query(self, sql: str, params: dict | None = None):
        params = params or {}
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT id FROM semantic_domain"):
            return [{"id": params["domain_id"]}] if params["domain_id"] in self.domains else []
        if "FROM enterprise_model_release" in normalized:
            rows = [
                dict(row)
                for row in self.releases.values()
                if int(row["domain_id"]) == int(params["domain_id"])
            ]
            if "id = :release_id" in normalized:
                rows = [row for row in rows if int(row["id"]) == int(params["release_id"])]
            if "status = 'active'" in normalized:
                rows = [row for row in rows if row["status"] == "active"]
            return sorted(rows, key=lambda row: int(row["version"]), reverse=True)
        return []

    async def execute(self, statement, params: dict | None = None):
        params = params or {}
        sql = " ".join(str(statement).split())
        if sql.startswith("SELECT id FROM semantic_domain"):
            rows = [{"id": params["domain_id"]}] if params["domain_id"] in self.domains else []
            return FakeResult(rows)
        if sql.startswith("SELECT id, domain_id, snapshot_json"):
            row = self.snapshots.get(int(params["semantic_snapshot_id"]))
            return FakeResult([dict(row)] if row else [])
        if sql.startswith("SELECT id, domain_id, definition_json"):
            row = self.ontology_releases.get(int(params["ontology_release_id"]))
            return FakeResult([dict(row)] if row else [])
        if sql.startswith("SELECT id FROM enterprise_model_release"):
            rows = [
                {"id": row["id"]}
                for row in self.releases.values()
                if row["domain_id"] == params["domain_id"]
                and row["semantic_snapshot_id"] == params["semantic_snapshot_id"]
                and row["ontology_release_id"] == params["ontology_release_id"]
            ]
            return FakeResult(rows)
        if sql.startswith("SELECT COALESCE(MAX(version)"):
            versions = [
                int(row["version"])
                for row in self.releases.values()
                if row["domain_id"] == params["domain_id"]
            ]
            return FakeResult([{"version": max(versions, default=0)}])
        if sql.startswith("SELECT") and "FROM enterprise_model_release" in sql:
            rows = [
                dict(row)
                for row in self.releases.values()
                if row["domain_id"] == params["domain_id"]
            ]
            if "id = :release_id" in sql:
                rows = [row for row in rows if row["id"] == params["release_id"]]
            if "status = 'active'" in sql:
                rows = [row for row in rows if row["status"] == "active"]
            return FakeResult(rows)
        if sql.startswith("INSERT INTO enterprise_model_release"):
            release_id = self.next_id
            self.next_id += 1
            self.releases[release_id] = {
                "id": release_id,
                **params,
                "status": "draft",
                "validation_json": None,
                "validated_by": None,
                "activated_by": None,
                "retired_by": None,
                "previous_active_release_id": None,
                "validated_at": None,
                "activated_at": None,
                "retired_at": None,
                "created_at": "2026-09-07T10:00:00",
                "updated_at": "2026-09-07T10:00:00",
            }
            return FakeResult(lastrowid=release_id, rowcount=1)
        if sql.startswith("UPDATE enterprise_model_release SET status = :status"):
            row = self.releases[int(params["release_id"])]
            row.update(params)
            row["validated_at"] = "2026-09-07T10:01:00"
            return FakeResult(rowcount=1)
        if sql.startswith("UPDATE enterprise_model_release SET status = 'retired'"):
            release_id = int(params.get("active_release_id") or params["release_id"])
            row = self.releases[release_id]
            row["status"] = "retired"
            row["retired_by"] = params.get("actor_id") or params.get("retired_by")
            row["retired_at"] = "2026-09-07T10:02:00"
            return FakeResult(rowcount=1)
        if sql.startswith("UPDATE enterprise_model_release SET status = 'active'"):
            row = self.releases[int(params["release_id"])]
            row["status"] = "active"
            row["activated_by"] = params["actor_id"]
            row["activated_at"] = "2026-09-07T10:03:00"
            row["retired_by"] = None
            row["retired_at"] = None
            row["previous_active_release_id"] = params["previous_active_release_id"]
            return FakeResult(rowcount=1)
        raise AssertionError(f"unexpected SQL: {sql}")


def test_release_schema_enforces_one_active_release_per_domain():
    ddl = "\n".join(MODEL_RELEASE_TABLE_STATEMENTS)

    assert "semantic_snapshot_id BIGINT NOT NULL" in ddl
    assert "ontology_release_id BIGINT NOT NULL" in ddl
    assert "model_hash CHAR(64) NOT NULL" in ddl
    assert "CASE WHEN status = 'active' THEN domain_id ELSE NULL END" in ddl
    assert "UNIQUE KEY uk_enterprise_model_release_active" in ddl


@pytest.mark.asyncio
async def test_get_active_release_is_optional_or_required(monkeypatch):
    db = ModelReleaseDB()
    monkeypatch.setattr(model_release_service, "get_management_db", lambda: db)
    service = ModelReleaseService()

    assert await service.get_active_release(9) is None
    with pytest.raises(ModelReleaseConflict, match="没有激活"):
        await service.get_active_release(9, required=True)

    release = await service.create_draft(
        9,
        EnterpriseModelReleaseCreatePayload(
            semantic_snapshot_id=10,
            ontology_release_id=20,
        ),
        created_by=1,
    )
    await service.validate_release(
        9,
        release["id"],
        EnterpriseModelValidationPayload(),
        validated_by=1,
    )
    await service.activate_release(9, release["id"], activated_by=1)

    active = await service.get_active_release(9, required=True)
    assert active is not None
    assert active["id"] == release["id"]
    assert active["status"] == "active"


@pytest.mark.asyncio
async def test_release_lifecycle_switches_active_and_supports_rollback(monkeypatch):
    db = ModelReleaseDB()
    monkeypatch.setattr(model_release_service, "get_management_db", lambda: db)
    service = ModelReleaseService()

    first = await service.create_draft(
        9,
        EnterpriseModelReleaseCreatePayload(
            semantic_snapshot_id=10,
            ontology_release_id=20,
            name="贷款模型 V1",
        ),
        created_by=1,
    )
    assert first["status"] == "draft"
    assert first["version"] == 1
    assert len(first["semantic_snapshot_hash"]) == 64
    assert len(first["model_hash"]) == 64

    first = await service.validate_release(
        9,
        first["id"],
        EnterpriseModelValidationPayload(checks={"business_terms": "passed"}),
        validated_by=1,
    )
    assert first["status"] == "validated"
    assert first["validation"]["valid"] is True
    first = await service.activate_release(9, first["id"], activated_by=1)
    assert first["status"] == "active"

    second = await service.create_draft(
        9,
        EnterpriseModelReleaseCreatePayload(
            semantic_snapshot_id=11,
            ontology_release_id=21,
        ),
        created_by=2,
    )
    await service.validate_release(
        9, second["id"], EnterpriseModelValidationPayload(), validated_by=2
    )
    second = await service.activate_release(9, second["id"], activated_by=2)

    assert second["status"] == "active"
    assert second["previous_active_release_id"] == first["id"]
    assert db.releases[first["id"]]["status"] == "retired"
    assert sum(row["status"] == "active" for row in db.releases.values()) == 1

    rolled_back = await service.rollback_release(9, first["id"], activated_by=3)
    assert rolled_back["status"] == "active"
    assert rolled_back["previous_active_release_id"] == second["id"]
    assert db.releases[second["id"]]["status"] == "retired"

    retired = await service.deactivate_release(9, first["id"], retired_by=3)
    assert retired["status"] == "retired"
    assert not any(row["status"] == "active" for row in db.releases.values())


@pytest.mark.asyncio
async def test_failed_validation_stays_draft_and_cannot_activate(monkeypatch):
    db = ModelReleaseDB()
    monkeypatch.setattr(model_release_service, "get_management_db", lambda: db)
    service = ModelReleaseService()
    release = await service.create_draft(
        9,
        EnterpriseModelReleaseCreatePayload(
            semantic_snapshot_id=10,
            ontology_release_id=20,
        ),
        created_by=1,
    )

    release = await service.validate_release(
        9,
        release["id"],
        EnterpriseModelValidationPayload(errors=["指标字段未映射"]),
        validated_by=1,
    )

    assert release["status"] == "draft"
    assert release["validation"]["errors"] == ["指标字段未映射"]
    with pytest.raises(ModelReleaseConflict, match="不能激活"):
        await service.activate_release(9, release["id"], activated_by=1)


@pytest.mark.asyncio
async def test_validation_detects_component_content_changed_after_draft(monkeypatch):
    db = ModelReleaseDB()
    monkeypatch.setattr(model_release_service, "get_management_db", lambda: db)
    service = ModelReleaseService()
    release = await service.create_draft(
        9,
        EnterpriseModelReleaseCreatePayload(
            semantic_snapshot_id=10,
            ontology_release_id=20,
        ),
        created_by=1,
    )
    original_hash = release["semantic_snapshot_hash"]
    db.snapshots[10]["snapshot_json"] = {"metrics": ["changed_after_draft"]}

    release = await service.validate_release(
        9,
        release["id"],
        EnterpriseModelValidationPayload(),
        validated_by=1,
    )

    assert release["status"] == "draft"
    assert release["semantic_snapshot_hash"] == original_hash
    assert "语义资产快照内容哈希与草稿创建时不一致" in release["validation"]["errors"]


@pytest.mark.asyncio
async def test_release_rejects_or_blocks_tampered_ontology_definition(monkeypatch):
    db = ModelReleaseDB()
    monkeypatch.setattr(model_release_service, "get_management_db", lambda: db)
    service = ModelReleaseService()

    db.ontology_releases[20]["definition_hash"] = "0" * 64
    with pytest.raises(ModelReleaseConflict, match="内容哈希"):
        await service.create_draft(
            9,
            EnterpriseModelReleaseCreatePayload(
                semantic_snapshot_id=10,
                ontology_release_id=20,
            ),
            created_by=1,
        )

    definition = db.ontology_releases[20]["definition_json"]
    db.ontology_releases[20]["definition_hash"] = canonical_sha256(definition)
    release = await service.create_draft(
        9,
        EnterpriseModelReleaseCreatePayload(
            semantic_snapshot_id=10,
            ontology_release_id=20,
        ),
        created_by=1,
    )
    db.ontology_releases[20]["definition_json"] = _ontology_definition("TamperedObject")

    validated = await service.validate_release(
        9,
        release["id"],
        EnterpriseModelValidationPayload(),
        validated_by=1,
    )

    assert validated["status"] == "draft"
    assert any("内容哈希" in item for item in validated["validation"]["errors"])


@pytest.mark.asyncio
async def test_activation_rechecks_component_integrity(monkeypatch):
    db = ModelReleaseDB()
    monkeypatch.setattr(model_release_service, "get_management_db", lambda: db)
    service = ModelReleaseService()
    release = await service.create_draft(
        9,
        EnterpriseModelReleaseCreatePayload(
            semantic_snapshot_id=10,
            ontology_release_id=20,
        ),
        created_by=1,
    )
    release = await service.validate_release(
        9,
        release["id"],
        EnterpriseModelValidationPayload(),
        validated_by=1,
    )
    assert release["status"] == "validated"

    db.ontology_releases[20]["definition_json"] = _ontology_definition("TamperedObject")

    with pytest.raises(ModelReleaseConflict, match="内容哈希"):
        await service.activate_release(9, release["id"], activated_by=1)


@pytest.mark.asyncio
async def test_server_validation_blocks_broken_snapshot_bridge_without_client_errors(
    monkeypatch,
):
    db = ModelReleaseDB()
    snapshot = db.snapshots[10]["snapshot_json"]
    snapshot["assets"]["metric"][0]["metadata"]["object_key"] = "MissingObject"
    monkeypatch.setattr(model_release_service, "get_management_db", lambda: db)
    service = ModelReleaseService()
    release = await service.create_draft(
        9,
        EnterpriseModelReleaseCreatePayload(
            semantic_snapshot_id=10,
            ontology_release_id=20,
        ),
        created_by=1,
    )

    validated = await service.validate_release(
        9,
        release["id"],
        EnterpriseModelValidationPayload(),
        validated_by=1,
    )

    assert validated["status"] == "draft"
    assert validated["validation"]["valid"] is False
    assert any(
        "MissingObject" in error for error in validated["validation"]["errors"]
    )


def test_unified_model_allows_ontology_link_without_query_path():
    snapshot, definition = _relation_components(relation_key=None)

    validation = _validate_component_payloads(9, snapshot, definition)

    assert validation["valid"] is True
    assert validation["checks"]["ontology_semantic_bridge"]["valid"] is True
    assert any("未找到同 key 的语义关系" in item for item in validation["warnings"])


def test_unified_model_validates_every_compound_relation_property():
    snapshot, definition = _relation_components()
    for object_type in definition["object_types"]:
        object_type["properties"].append(
            {
                "property_key": "tenant_id",
                "name": "租户标识",
                "data_type": "string",
                "required": True,
                "unique": False,
                "sort_order": 1,
            }
        )
    definition["link_types"][0].update(
        {
            "source_property_keys": ["tenant_id", "record_id"],
            "target_property_keys": ["tenant_id", "record_id"],
            "source_property": "tenant_id",
            "target_property": "tenant_id",
        }
    )

    validation = _validate_component_payloads(9, snapshot, definition)

    assert validation["valid"] is True


@pytest.mark.parametrize(
    ("relation_key", "source", "target", "message"),
    [
        (
            "unbound_customer_application_path",
            "Customer",
            "LoanApplication",
            "未显式绑定已生效的本体关系",
        ),
        (
            "customer_submits_application",
            "LoanApplication",
            "Customer",
            "起点或终点方向不一致",
        ),
    ],
)
def test_unified_model_blocks_invalid_semantic_relation_binding(
    relation_key,
    source,
    target,
    message,
):
    snapshot, definition = _relation_components(
        relation_key=relation_key,
        source=source,
        target=target,
    )

    validation = _validate_component_payloads(9, snapshot, definition)

    assert validation["valid"] is False
    assert validation["checks"]["ontology_semantic_bridge"]["valid"] is False
    assert any(message in item for item in validation["errors"])


@pytest.mark.asyncio
async def test_release_validation_keeps_reversed_semantic_relation_in_draft(
    monkeypatch,
):
    db = ModelReleaseDB()
    snapshot, definition = _relation_components(
        source="LoanApplication",
        target="Customer",
    )
    db.snapshots[10]["snapshot_json"] = snapshot
    db.ontology_releases[20]["definition_json"] = definition
    db.ontology_releases[20]["definition_hash"] = canonical_sha256(definition)
    monkeypatch.setattr(model_release_service, "get_management_db", lambda: db)
    service = ModelReleaseService()
    release = await service.create_draft(
        9,
        EnterpriseModelReleaseCreatePayload(
            semantic_snapshot_id=10,
            ontology_release_id=20,
        ),
        created_by=1,
    )

    validated = await service.validate_release(
        9,
        release["id"],
        EnterpriseModelValidationPayload(),
        validated_by=1,
    )

    assert validated["status"] == "draft"
    assert validated["validation"]["valid"] is False
    assert any(
        "方向不一致" in item for item in validated["validation"]["errors"]
    )


@pytest.mark.asyncio
async def test_release_rejects_cross_domain_or_duplicate_components(monkeypatch):
    db = ModelReleaseDB()
    monkeypatch.setattr(model_release_service, "get_management_db", lambda: db)
    service = ModelReleaseService()
    payload = EnterpriseModelReleaseCreatePayload(
        semantic_snapshot_id=10,
        ontology_release_id=20,
    )

    await service.create_draft(9, payload, created_by=1)
    with pytest.raises(ModelReleaseConflict, match="已建立发布记录"):
        await service.create_draft(9, payload, created_by=1)
    with pytest.raises(ModelReleaseConflict, match="不属于当前业务领域"):
        await service.create_draft(
            9,
            EnterpriseModelReleaseCreatePayload(
                semantic_snapshot_id=12,
                ontology_release_id=20,
            ),
            created_by=1,
        )


def test_validation_payload_is_serializable():
    payload = EnterpriseModelValidationPayload(
        warnings=["缺少业务示例问题"], checks={"mapping_count": 3}
    )
    assert json.loads(payload.model_dump_json())["checks"] == {"mapping_count": 3}
