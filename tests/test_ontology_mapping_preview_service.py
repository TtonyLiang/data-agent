from __future__ import annotations

import pytest

from app.models.ontology import OntologyObjectTypePayload
from app.services import ontology_mapping_preview_service as preview_module
from app.services.ontology_mapping_preview_service import (
    OntologyMappingPreviewService,
)
from app.services.permission_service import PermissionRuntimeContext


class PreviewSourceDB:
    def __init__(self, rows, *, total=None, empty=0, distinct=None):
        self.rows = rows
        self.total = len(rows) if total is None else total
        self.empty = empty
        self.distinct = len(rows) if distinct is None else distinct
        self.queries: list[tuple[str, dict]] = []

    async def execute_query(self, sql, params=None):
        self.queries.append((sql, params or {}))
        if "COUNT(*) AS total_rows" in sql:
            return [{
                "total_rows": self.total,
                "empty_primary_rows": self.empty,
                "distinct_primary_rows": self.distinct,
            }]
        return list(self.rows)


class PreviewOntology:
    def __init__(self, object_type):
        self.object_type = object_type

    async def _require_domain(self, domain_id):
        return {"id": domain_id, "datasource_id": 8, "status": "active"}

    async def _load_object_permission_context(self, _domain, _access_agent_id):
        return PermissionRuntimeContext(
            domain_id=4,
            datasource_id=8,
            source="domain",
            table_permissions={"tax_invoice": True},
            column_permissions={},
        )

    def _validated_source_query(self, source_query):
        return source_query

    async def list_link_types(self, _domain_id):
        return []


def payload(**overrides):
    value = {
        "domain_id": 4,
        "object_key": "TaxInvoice",
        "name": "发票",
        "primary_property": "invoice_id",
        "display_property": "invoice_no",
        "sync_enabled": True,
        "source_query": (
            "SELECT invoice_id, invoice_no, amount "
            "FROM tax_invoice ORDER BY invoice_id"
        ),
        "properties": [
            {
                "property_key": "invoice_id",
                "name": "发票ID",
                "data_type": "integer",
                "required": True,
                "unique": True,
            },
            {
                "property_key": "invoice_no",
                "name": "发票号码",
                "data_type": "string",
                "required": True,
            },
            {
                "property_key": "amount",
                "name": "金额",
                "data_type": "number",
                "required": True,
            },
        ],
    }
    value.update(overrides)
    return OntologyObjectTypePayload.model_validate(value)


@pytest.mark.asyncio
async def test_mapping_preview_checks_permissions_mapping_and_returns_samples(monkeypatch):
    source = PreviewSourceDB(
        [
            {"invoice_id": "1001", "invoice_no": "INV-001", "amount": "12.50"},
            {"invoice_id": "1002", "invoice_no": "INV-002", "amount": 8},
        ],
        total=2,
        distinct=2,
    )
    object_type = payload()
    monkeypatch.setattr(
        preview_module,
        "get_ontology_service",
        lambda: PreviewOntology(object_type),
    )
    monkeypatch.setattr(
        preview_module,
        "get_datasource_db",
        lambda _datasource_id: _async_value(source),
    )

    result = await OntologyMappingPreviewService().preview(object_type)

    assert result["valid"] is True
    assert result["query"]["tables"] == ["tax_invoice"]
    assert result["mapping"]["missing"] == []
    assert result["statistics"]["total_rows"] == 2
    assert result["sample_rows"][0] == {
        "invoice_id": 1001,
        "invoice_no": "INV-001",
        "amount": 12.5,
    }
    assert len(source.queries) == 2


@pytest.mark.asyncio
async def test_mapping_preview_reports_required_columns_type_errors_and_duplicate_keys(
    monkeypatch,
):
    source = PreviewSourceDB(
        [
            {"invoice_id": "bad", "invoice_no": "INV-001", "amount": "1"},
            {"invoice_id": "1", "invoice_no": "INV-002", "amount": "2"},
        ],
        total=3,
        distinct=1,
    )
    object_type = payload(
        properties=[
            {
                "property_key": "invoice_id",
                "name": "发票ID",
                "data_type": "integer",
                "required": True,
                "unique": True,
            },
            {
                "property_key": "invoice_no",
                "name": "发票号码",
                "data_type": "string",
                "required": True,
            },
            {
                "property_key": "missing_required",
                "name": "缺失字段",
                "data_type": "string",
                "required": True,
            },
        ]
    )
    monkeypatch.setattr(
        preview_module,
        "get_ontology_service",
        lambda: PreviewOntology(object_type),
    )
    monkeypatch.setattr(
        preview_module,
        "get_datasource_db",
        lambda _datasource_id: _async_value(source),
    )

    result = await OntologyMappingPreviewService().preview(object_type)

    assert result["valid"] is False
    assert any(item["code"] == "missing_required_property" for item in result["errors"])
    assert any(item["code"] == "type_conversion" for item in result["errors"])
    assert any(item["code"] == "duplicate_primary_values" for item in result["errors"])
    # The statistic counts duplicate rows beyond the first occurrence of a key.
    assert result["statistics"]["duplicate_primary_rows"] == 2


@pytest.mark.asyncio
async def test_mapping_preview_rejects_unconfigured_domain_permission(monkeypatch):
    object_type = payload()

    class UnconfiguredOntology(PreviewOntology):
        async def _load_object_permission_context(self, _domain, _access_agent_id):
            return PermissionRuntimeContext(
                domain_id=4,
                datasource_id=8,
                source="unconfigured",
                table_permissions={},
                column_permissions={},
            )

    monkeypatch.setattr(
        preview_module,
        "get_ontology_service",
        lambda: UnconfiguredOntology(object_type),
    )

    with pytest.raises(PermissionError, match="未配置数据权限"):
        await OntologyMappingPreviewService().preview(object_type)


async def _async_value(value):
    return value
