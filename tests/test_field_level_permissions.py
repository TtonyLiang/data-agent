import pytest
from fastapi import HTTPException

from app.api import ontology as ontology_api
from app.api import semantic as semantic_api
from app.models.knowledge import SemanticAssetPayload, SemanticDomain
from app.models.ontology import (
    OntologyActionTypePayload,
    OntologyImportPayload,
    OntologyLinkTypePayload,
)
from app.models.user import PublicUser

ADMIN = PublicUser(id=1, username="admin", role="admin", status="active")
BUSINESS = PublicUser(id=2, username="business", role="business", status="active")


class SemanticPermissionService:
    def __init__(self, assets=None):
        self.assets = assets or {}
        self.upserts = []
        self.imported_bundle = None

    async def get_domain(self, domain_id):
        return SemanticDomain(id=domain_id, domain_key="loan_risk", name="贷款风控")

    async def list_assets(self, domain_id, asset_type=None):
        if asset_type:
            return {asset_type: list(self.assets.get(asset_type, []))}
        return {key: list(value) for key, value in self.assets.items()}

    async def upsert_asset(self, domain_id, asset_type, data):
        self.upserts.append((domain_id, asset_type, data))
        return 88

    async def import_domain_bundle(self, bundle):
        self.imported_bundle = bundle
        return 7


@pytest.mark.asyncio
async def test_business_metric_update_preserves_existing_technical_fields(monkeypatch):
    service = SemanticPermissionService(
        {
            "metric": [
                {
                    "id": 3,
                    "metric_key": "application_count",
                    "name": "申请数量",
                    "formula_sql": "COUNT(*)",
                    "base_table": "loan_application",
                    "time_field": "loan_application.created_at",
                }
            ]
        }
    )
    monkeypatch.setattr(semantic_api, "get_semantic_runtime_service", lambda: service)

    result = await semantic_api.upsert_asset(
        7,
        SemanticAssetPayload(
            asset_type="metric",
            data={"id": 3, "metric_key": "application_count", "name": "申请笔数"},
        ),
        BUSINESS,
    )

    assert result["id"] == 88
    saved = service.upserts[0][2]
    assert saved["name"] == "申请笔数"
    assert saved["formula_sql"] == "COUNT(*)"
    assert saved["base_table"] == "loan_application"
    assert saved["time_field"] == "loan_application.created_at"


@pytest.mark.asyncio
async def test_business_metric_cannot_set_sql_or_table(monkeypatch):
    service = SemanticPermissionService()
    monkeypatch.setattr(semantic_api, "get_semantic_runtime_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await semantic_api.upsert_asset(
            7,
            SemanticAssetPayload(
                asset_type="metric",
                data={
                    "metric_key": "application_count",
                    "name": "申请笔数",
                    "formula_sql": "COUNT(*)",
                    "base_table": "loan_application",
                },
            ),
            BUSINESS,
        )

    assert exc_info.value.status_code == 403
    assert service.upserts == []


@pytest.mark.asyncio
async def test_business_cannot_maintain_mapping_assets(monkeypatch):
    service = SemanticPermissionService()
    monkeypatch.setattr(semantic_api, "get_semantic_runtime_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await semantic_api.upsert_asset(
            7,
            SemanticAssetPayload(
                asset_type="mapping",
                data={
                    "asset_type": "dimension",
                    "asset_key": "channel",
                    "table_name": "loan_application",
                },
            ),
            BUSINESS,
        )

    assert exc_info.value.status_code == 403
    assert service.upserts == []


@pytest.mark.asyncio
async def test_business_relation_update_preserves_existing_join_path(monkeypatch):
    relation = {
        "id": 4,
        "relation_key": "customer_submits_application",
        "relation_type": "join_path",
        "source_concept": "Customer",
        "target_concept": "LoanApplication",
        "name": "客户提交申请",
        "join_path": [{"left": "customer.customer_id", "right": "loan.customer_id"}],
        "conditions": [{"field": "loan.status", "operator": "!=", "value": "deleted"}],
    }
    service = SemanticPermissionService({"relation": [relation]})
    monkeypatch.setattr(semantic_api, "get_semantic_runtime_service", lambda: service)
    class RelationOntologyService:
        async def list_link_types(self, domain_id):
            return [
                {
                    "link_key": "customer_submits_application",
                    "source_object_key": "Customer",
                    "target_object_key": "LoanApplication",
                    "status": "active",
                }
            ]

    monkeypatch.setattr(semantic_api, "get_ontology_service", lambda: RelationOntologyService())

    result = await semantic_api.upsert_asset(
        7,
        SemanticAssetPayload(
            asset_type="relation",
            data={
                "id": 4,
                "relation_key": "customer_submits_application",
                "relation_type": "join_path",
                "source_concept": "Customer",
                "target_concept": "LoanApplication",
                "name": "客户提交贷款申请",
            },
        ),
        BUSINESS,
    )

    assert result["id"] == 88
    saved = service.upserts[0][2]
    assert saved["name"] == "客户提交贷款申请"
    assert saved["join_path"] == relation["join_path"]
    assert saved["conditions"] == relation["conditions"]


@pytest.mark.asyncio
async def test_business_relation_cannot_change_join_path(monkeypatch):
    service = SemanticPermissionService({"relation": []})
    monkeypatch.setattr(semantic_api, "get_semantic_runtime_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await semantic_api.upsert_asset(
            7,
            SemanticAssetPayload(
                asset_type="relation",
                data={
                    "relation_key": "customer_submits_application",
                    "relation_type": "join_path",
                    "source_concept": "Customer",
                    "target_concept": "LoanApplication",
                    "name": "客户提交申请",
                    "join_path": [{"left": "customer.id", "right": "loan.customer_id"}],
                },
            ),
            BUSINESS,
        )

    assert exc_info.value.status_code == 403
    assert service.upserts == []


@pytest.mark.asyncio
async def test_business_relation_cannot_change_ontology_binding_metadata(monkeypatch):
    service = SemanticPermissionService(
        {
            "relation": [
                {
                    "id": 4,
                    "relation_key": "customer_submits_application",
                    "relation_type": "join_path",
                    "source_concept": "Customer",
                    "target_concept": "LoanApplication",
                    "name": "客户提交申请",
                    "join_path": [],
                    "conditions": [],
                    "metadata": {"link_key": "customer_submits_application"},
                }
            ]
        }
    )
    monkeypatch.setattr(semantic_api, "get_semantic_runtime_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await semantic_api.upsert_asset(
            7,
            SemanticAssetPayload(
                asset_type="relation",
                data={
                    "id": 4,
                    "relation_key": "customer_submits_application",
                    "relation_type": "join_path",
                    "source_concept": "Customer",
                    "target_concept": "LoanApplication",
                    "name": "客户提交申请",
                    "metadata": {"link_key": "other_link"},
                },
            ),
            BUSINESS,
        )

    assert exc_info.value.status_code == 403
    assert service.upserts == []


@pytest.mark.asyncio
async def test_business_template_cannot_change_compile_strategy(monkeypatch):
    service = SemanticPermissionService(
        {
            "template": [
                {
                    "id": 5,
                    "template_key": "metric_query",
                    "name": "指标查询",
                    "intent_type": "metric_query",
                    "compile_strategy": {"type": "metric_select"},
                }
            ]
        }
    )
    monkeypatch.setattr(semantic_api, "get_semantic_runtime_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await semantic_api.upsert_asset(
            7,
            SemanticAssetPayload(
                asset_type="template",
                data={
                    "id": 5,
                    "template_key": "metric_query",
                    "name": "指标查询",
                    "intent_type": "metric_query",
                    "compile_strategy": {"type": "metadata_select"},
                },
            ),
            BUSINESS,
        )

    assert exc_info.value.status_code == 403
    assert service.upserts == []


@pytest.mark.asyncio
async def test_business_semantic_bundle_import_allows_business_only_assets(monkeypatch):
    service = SemanticPermissionService()
    monkeypatch.setattr(semantic_api, "get_semantic_runtime_service", lambda: service)

    result = await semantic_api.import_domain(
        {
            "domain": {"domain_key": "loan_risk", "name": "贷款风控"},
            "assets": {
                "metric": [{"metric_key": "application_count", "name": "申请笔数"}],
                "template": [
                    {
                        "template_key": "metric_query",
                        "intent_type": "metric_query",
                        "name": "指标查询",
                    }
                ],
            },
        },
        BUSINESS,
    )

    assert result["id"] == 7
    metric = service.imported_bundle["assets"]["metric"][0]
    assert metric["formula_sql"] == ""
    assert metric["base_table"] == ""
    assert metric["time_field"] is None
    assert service.imported_bundle["assets"]["template"][0]["compile_strategy"] == {}


@pytest.mark.asyncio
async def test_business_semantic_bundle_import_rejects_technical_fields(monkeypatch):
    service = SemanticPermissionService()
    monkeypatch.setattr(semantic_api, "get_semantic_runtime_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await semantic_api.import_domain(
            {
                "domain": {"domain_key": "loan_risk", "name": "贷款风控"},
                "assets": {
                    "metric": [
                        {
                            "metric_key": "application_count",
                            "name": "申请笔数",
                            "formula_sql": "COUNT(*)",
                        }
                    ]
                },
            },
            BUSINESS,
        )

    assert exc_info.value.status_code == 403
    assert service.imported_bundle is None


class OntologyPermissionService:
    def __init__(self, link_types=None, action_types=None):
        self.link_types = link_types or []
        self.action_types = action_types or []
        self.saved_links = []
        self.saved_actions = []
        self.imported = None

    async def list_object_types(self, domain_id):
        return [
            {
                "id": 11,
                "object_key": "Customer",
                "name": "客户",
                "primary_property": "customer_id",
                "properties": [{"property_key": "customer_id"}, {"property_key": "phone"}],
            },
            {
                "id": 12,
                "object_key": "LoanApplication",
                "name": "贷款申请",
                "primary_property": "application_id",
                "properties": [{"property_key": "application_id"}, {"property_key": "customer_id"}],
            },
        ]

    async def get_object_type(self, domain_id, object_type_id=None, object_key=None):
        for item in await self.list_object_types(domain_id):
            if item["object_key"] == object_key or item["id"] == object_type_id:
                return item
        return None

    async def list_link_types(self, domain_id):
        return list(self.link_types)

    async def upsert_link_type(self, payload):
        self.saved_links.append(payload)
        return 31

    async def list_action_types(self, domain_id):
        return list(self.action_types)

    async def upsert_action_type(self, payload):
        self.saved_actions.append(payload)
        return 41

    async def import_bundle(self, domain_id, bundle, replace=False):
        self.imported = (domain_id, bundle, replace)
        return {"object_types": 2, "link_types": 1, "action_types": 1, "objects": 0, "links": 0}


def link_payload(**overrides):
    data = {
        "domain_id": 7,
        "link_key": "customer_submits_application",
        "name": "客户提交申请",
        "source_object_key": "Customer",
        "target_object_key": "LoanApplication",
        "cardinality": "one_to_many",
        "description": "业务关系",
    }
    data.update(overrides)
    return OntologyLinkTypePayload(**data)


def action_payload(**overrides):
    data = {
        "domain_id": 7,
        "action_key": "approve_application",
        "name": "审批申请",
        "target_object_key": "LoanApplication",
        "description": "业务动作",
    }
    data.update(overrides)
    return OntologyActionTypePayload(**data)


@pytest.mark.asyncio
async def test_business_can_create_link_with_default_relation_keys(monkeypatch):
    service = OntologyPermissionService()
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: service)

    result = await ontology_api.upsert_link_type(7, link_payload(), BUSINESS)

    assert result["id"] == 31
    assert service.saved_links[0].source_property is None
    assert service.saved_links[0].source_property_keys is None


@pytest.mark.asyncio
async def test_business_cannot_override_link_relation_keys(monkeypatch):
    service = OntologyPermissionService()
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await ontology_api.upsert_link_type(
            7,
            link_payload(source_property="phone", target_property="customer_id"),
            BUSINESS,
        )

    assert exc_info.value.status_code == 403
    assert service.saved_links == []


@pytest.mark.asyncio
async def test_business_action_can_change_preconditions_but_not_governance(monkeypatch):
    service = OntologyPermissionService(
        action_types=[
            {
                "id": 5,
                "action_key": "approve_application",
                "allowed_roles": ["admin"],
                "requires_approval": False,
            }
        ]
    )
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: service)

    result = await ontology_api.upsert_action_type(
        7,
        action_payload(
            id=5,
            preconditions=[{"property": "status", "operator": "eq", "value": "manual_review"}],
            effects=[{"property": "status", "value": "approved"}],
        ),
        BUSINESS,
    )

    assert result["id"] == 41
    assert service.saved_actions[0].preconditions[0].property == "status"
    assert service.saved_actions[0].effects[0].value == "approved"

    with pytest.raises(HTTPException) as exc_info:
        await ontology_api.upsert_action_type(
            7,
            action_payload(id=5, allowed_roles=["user"], requires_approval=True),
            BUSINESS,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_business_action_cannot_change_technical_identity_status_or_parameter_key(
    monkeypatch,
):
    service = OntologyPermissionService(
        action_types=[
            {
                "id": 5,
                "action_key": "approve_application",
                "allowed_roles": ["admin"],
                "requires_approval": False,
                "status": "draft",
                "parameters": [
                    {
                        "parameter_key": "approval_reason",
                        "name": "审批原因",
                        "data_type": "string",
                    }
                ],
            }
        ]
    )
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: service)

    blocked_payloads = [
        action_payload(id=5, action_key="approve_application_v2"),
        action_payload(id=5, status="active"),
        action_payload(
            id=5,
            parameters=[{"parameter_key": "changed_reason", "name": "审批原因"}],
        ),
    ]
    for payload in blocked_payloads:
        with pytest.raises(HTTPException) as exc_info:
            await ontology_api.upsert_action_type(7, payload, BUSINESS)
        assert exc_info.value.status_code == 403

    assert service.saved_actions == []


@pytest.mark.asyncio
async def test_business_link_cannot_change_technical_identity_or_status(monkeypatch):
    service = OntologyPermissionService(
        link_types=[
            {
                "id": 9,
                "link_key": "customer_submits_application",
                "name": "客户提交申请",
                "source_object_key": "Customer",
                "target_object_key": "LoanApplication",
                "source_property_keys": ["customer_id"],
                "target_property_keys": ["application_id"],
                "status": "draft",
            }
        ]
    )
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: service)

    for payload in [
        link_payload(id=9, link_key="customer_applies"),
        link_payload(id=9, status="active"),
    ]:
        with pytest.raises(HTTPException) as exc_info:
            await ontology_api.upsert_link_type(7, payload, BUSINESS)
        assert exc_info.value.status_code == 403

    assert service.saved_links == []


@pytest.mark.asyncio
async def test_business_ontology_bundle_import_allows_default_technical_values(monkeypatch):
    service = OntologyPermissionService()
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: service)

    bundle = {
        "format": "wenqu-ontology",
        "version": 1,
        "object_types": [
            {
                "object_key": "Customer",
                "name": "客户",
                "primary_property": "customer_id",
                "properties": [{"property_key": "customer_id", "name": "客户号"}],
            },
            {
                "object_key": "LoanApplication",
                "name": "贷款申请",
                "primary_property": "application_id",
                "properties": [{"property_key": "application_id", "name": "申请号"}],
            },
        ],
        "link_types": [
            {
                "link_key": "customer_submits_application",
                "name": "客户提交申请",
                "source_object_key": "Customer",
                "target_object_key": "LoanApplication",
                "source_property": "customer_id",
                "target_property": "application_id",
            }
        ],
        "action_types": [
            {
                "action_key": "approve_application",
                "name": "审批申请",
                "target_object_key": "LoanApplication",
                "allowed_roles": ["admin"],
                "requires_approval": False,
            }
        ],
    }

    result = await ontology_api.import_bundle(
        7, OntologyImportPayload(bundle=bundle), BUSINESS
    )

    assert result["imported"]["object_types"] == 2
    assert service.imported[1] == bundle


@pytest.mark.asyncio
async def test_business_ontology_bundle_import_rejects_technical_fields(monkeypatch):
    service = OntologyPermissionService()
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: service)

    bundle = {
        "format": "wenqu-ontology",
        "version": 1,
        "object_types": [
            {
                "object_key": "Customer",
                "name": "客户",
                "primary_property": "customer_id",
                "source_query": "SELECT * FROM customer",
                "properties": [{"property_key": "customer_id", "name": "客户号"}],
            }
        ],
    }

    with pytest.raises(HTTPException) as exc_info:
        await ontology_api.import_bundle(7, OntologyImportPayload(bundle=bundle), BUSINESS)

    assert exc_info.value.status_code == 403
    assert service.imported is None


@pytest.mark.asyncio
async def test_business_ontology_bundle_import_rejects_replace_and_instances(monkeypatch):
    service = OntologyPermissionService()
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: service)
    bundle = {
        "format": "wenqu-ontology",
        "version": 1,
        "object_types": [
            {
                "object_key": "Customer",
                "name": "客户",
                "primary_property": "customer_id",
                "properties": [{"property_key": "customer_id", "name": "客户号"}],
            }
        ],
    }

    with pytest.raises(HTTPException) as exc_info:
        await ontology_api.import_bundle(
            7,
            OntologyImportPayload(bundle=bundle, replace=True),
            BUSINESS,
        )
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        await ontology_api.import_bundle(
            7,
            OntologyImportPayload(bundle={**bundle, "objects": [{"object_type_key": "Customer"}]}),
            BUSINESS,
        )
    assert exc_info.value.status_code == 403
    assert service.imported is None


@pytest.mark.asyncio
async def test_admin_can_import_technical_ontology_bundle_with_replace(monkeypatch):
    service = OntologyPermissionService()
    monkeypatch.setattr(ontology_api, "get_ontology_service", lambda: service)
    bundle = {
        "format": "wenqu-ontology",
        "version": 1,
        "object_types": [
            {
                "object_key": "Customer",
                "name": "客户",
                "primary_property": "customer_id",
                "sync_enabled": True,
                "source_query": "SELECT customer_id FROM customer ORDER BY customer_id",
                "properties": [{"property_key": "customer_id", "name": "客户号"}],
            }
        ],
    }

    result = await ontology_api.import_bundle(
        7,
        OntologyImportPayload(bundle=bundle, replace=True),
        ADMIN,
    )

    assert result["imported"]["object_types"] == 2
    assert service.imported == (7, bundle, True)
