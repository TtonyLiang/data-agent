import pytest
from fastapi import HTTPException

from app.api import semantic as semantic_api
from app.models.knowledge import SemanticAssetPayload, SemanticDomain
from app.models.user import PublicUser

ADMIN = PublicUser(id=1, username="admin", role="admin", status="active")
BUSINESS = PublicUser(id=2, username="business", role="business", status="active")


def relation_payload(
    *,
    relation_key="customer_submits_application",
    source="Customer",
    target="LoanApplication",
):
    return SemanticAssetPayload(
        asset_type="relation",
        data={
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
        },
    )


class OntologyService:
    async def list_link_types(self, domain_id):
        assert domain_id == 7
        return [
            {
                "link_key": "customer_submits_application",
                "source_object_key": "Customer",
                "target_object_key": "LoanApplication",
                "status": "active",
            }
        ]


class DraftOntologyService(OntologyService):
    async def list_link_types(self, domain_id):
        links = await super().list_link_types(domain_id)
        links[0]["status"] = "draft"
        return links


class SemanticService:
    def __init__(self, relation=None):
        self.relation = relation
        self.upserts = []

    async def get_domain(self, domain_id):
        return SemanticDomain(
            id=domain_id,
            domain_key="loan_risk",
            name="贷款风控",
        )

    async def upsert_asset(self, domain_id, asset_type, data):
        self.upserts.append((domain_id, asset_type, data))
        return 19

    async def validate_domain_assets(self, domain_id):
        assert domain_id == 7
        return {"valid": True, "errors": [], "warnings": [], "asset_counts": {}}

    async def list_assets(self, domain_id, asset_type):
        assert (domain_id, asset_type) == (7, "relation")
        return {"relation": [self.relation] if self.relation else []}


@pytest.mark.asyncio
async def test_semantic_relation_upsert_requires_existing_ontology_link(monkeypatch):
    service = SemanticService()
    monkeypatch.setattr(
        semantic_api, "get_semantic_runtime_service", lambda: service
    )
    monkeypatch.setattr(
        semantic_api, "get_ontology_service", lambda: OntologyService()
    )

    result = await semantic_api.upsert_asset(7, relation_payload(), ADMIN)

    assert result["id"] == 19
    assert service.upserts[0][1] == "relation"


@pytest.mark.asyncio
async def test_semantic_relation_can_be_drafted_before_ontology_link_is_active(
    monkeypatch,
):
    service = SemanticService()
    monkeypatch.setattr(
        semantic_api, "get_semantic_runtime_service", lambda: service
    )
    monkeypatch.setattr(
        semantic_api, "get_ontology_service", lambda: DraftOntologyService()
    )

    result = await semantic_api.upsert_asset(7, relation_payload(), ADMIN)

    assert result["id"] == 19
    assert service.upserts[0][1] == "relation"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        relation_payload(relation_key="unbound_query_path"),
        relation_payload(source="LoanApplication", target="Customer"),
    ],
)
async def test_semantic_relation_upsert_rejects_orphan_or_reversed_binding(
    monkeypatch, payload
):
    service = SemanticService()
    monkeypatch.setattr(
        semantic_api, "get_semantic_runtime_service", lambda: service
    )
    monkeypatch.setattr(
        semantic_api, "get_ontology_service", lambda: OntologyService()
    )

    with pytest.raises(HTTPException) as exc_info:
        await semantic_api.upsert_asset(7, payload, ADMIN)

    assert exc_info.value.status_code == 400
    assert service.upserts == []


@pytest.mark.asyncio
async def test_semantic_domain_validation_blocks_reversed_relation(monkeypatch):
    relation = relation_payload(
        source="LoanApplication", target="Customer"
    ).data
    service = SemanticService(relation)
    monkeypatch.setattr(
        semantic_api, "get_semantic_runtime_service", lambda: service
    )
    monkeypatch.setattr(
        semantic_api, "get_ontology_service", lambda: OntologyService()
    )

    result = await semantic_api.validate_domain(7, ADMIN)

    assert result["valid"] is False
    assert any("方向不一致" in item for item in result["errors"])
    assert result["checks"]["ontology_relation_bindings"]["valid"] is False


@pytest.mark.asyncio
async def test_business_domain_edit_cannot_change_datasource_or_agent_binding(monkeypatch):
    class DomainService:
        def __init__(self):
            self.saved = []

        async def get_domain(self, domain_id):
            return SemanticDomain(
                id=domain_id,
                agent_id=7,
                datasource_id=11,
                domain_key="loan_risk",
                name="贷款风控",
            )

        async def upsert_domain(self, data):
            self.saved.append(data)
            return 7

    service = DomainService()
    monkeypatch.setattr(semantic_api, "get_semantic_runtime_service", lambda: service)
    payload = SemanticDomain(
        id=7,
        agent_id=7,
        datasource_id=12,
        domain_key="loan_risk",
        name="贷款风控（业务说明更新）",
    )

    with pytest.raises(HTTPException) as exc_info:
        await semantic_api.upsert_domain(payload, BUSINESS)

    assert exc_info.value.status_code == 403
    assert service.saved == []


@pytest.mark.asyncio
async def test_business_domain_edit_preserves_technical_bindings(monkeypatch):
    class DomainService:
        async def get_domain(self, domain_id):
            return SemanticDomain(
                id=domain_id,
                agent_id=7,
                datasource_id=11,
                domain_key="loan_risk",
                name="贷款风控",
            )

        async def upsert_domain(self, data):
            assert data["agent_id"] == 7
            assert data["datasource_id"] == 11
            assert data["name"] == "贷款风控（业务说明更新）"
            return 7

    service = DomainService()
    monkeypatch.setattr(semantic_api, "get_semantic_runtime_service", lambda: service)
    payload = SemanticDomain(
        id=7,
        agent_id=7,
        datasource_id=11,
        domain_key="loan_risk",
        name="贷款风控（业务说明更新）",
    )

    result = await semantic_api.upsert_domain(payload, BUSINESS)

    assert result["id"] == 7
