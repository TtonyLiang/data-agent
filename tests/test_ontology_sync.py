import copy
import json
from typing import Any

import pytest

from app.services import ontology_service
from app.services.ontology_service import OntologyService

DOMAIN_ID = 4
DATASOURCE_ID = 42


def _property(
    key: str,
    data_type: str = "string",
    *,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "property_key": key,
        "name": key,
        "data_type": data_type,
        "required": required,
        "unique": False,
        "default_value": None,
    }


def _loan_account_type(*, sync_enabled: bool = True, source_query: str | None = None):
    return {
        "id": 11,
        "domain_id": DOMAIN_ID,
        "object_key": "LoanAccount",
        "name": "贷款账户",
        "primary_property": "loan_id",
        "display_property": "loan_no",
        "sync_enabled": sync_enabled,
        "source_query": source_query
        or (
            "SELECT loan_id, loan_no, collection_status, balance "
            "FROM loan_account_indicator ORDER BY loan_id"
        ),
        "sync_limit": 200,
        "status": "active",
        "properties": [
            _property("loan_id", "integer"),
            _property("loan_no"),
            _property("collection_status"),
            _property("balance", "number"),
        ],
    }


def _loan_row(index: int, *, balance: int = 1000) -> dict[str, Any]:
    return {
        "loan_id": index,
        "loan_no": f"LN-{index:04d}",
        "collection_status": "not_started",
        "balance": balance,
    }


class FakeSourceDB:
    def __init__(self, rows_by_marker: dict[str, list[dict[str, Any]]]):
        self.rows_by_marker = rows_by_marker
        self.queries: list[tuple[str, dict[str, Any]]] = []

    async def execute_query(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        bound = dict(params or {})
        self.queries.append((sql, bound))
        marker = next((item for item in self.rows_by_marker if item in sql), None)
        if marker is None:
            raise AssertionError(f"unexpected business query: {sql}")
        rows = self.rows_by_marker[marker]
        if "SELECT COUNT(*) AS count" in sql:
            return [{"count": len(rows)}]
        offset = int(bound["sync_offset"])
        limit = int(bound["sync_limit"])
        return copy.deepcopy(rows[offset : offset + limit])


class FakeManagementDB:
    def __init__(self, objects: list[dict[str, Any]] | None = None):
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self.inserts: list[tuple[str, dict[str, Any], int]] = []
        self.object_updates: list[dict[str, Any]] = []
        self.transactions: list[list[tuple[str, dict[str, Any]]]] = []
        self.next_id = 1000
        self.objects: dict[tuple[int, str], dict[str, Any]] = {}
        for item in objects or []:
            self.objects[(int(item["object_type_id"]), str(item["primary_value"]))] = (
                copy.deepcopy(item)
            )

    async def execute_query(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        bound = dict(params or {})
        self.queries.append((sql, bound))
        normalized = " ".join(sql.split())

        if normalized.startswith("SELECT * FROM ontology_object WHERE domain_id"):
            key = (int(bound["object_type_id"]), str(bound["primary_value"]))
            item = self.objects.get(key)
            return [copy.deepcopy(item)] if item else []

        if "JSON_UNQUOTE(JSON_EXTRACT(o.properties" in normalized:
            object_type_key = str(bound["object_type_key"])
            json_path = str(bound["json_path"])
            property_key = json_path.removeprefix('$."').removesuffix('"')
            values = {
                str(value) for key, value in bound.items() if key.startswith("value_")
            }
            return [
                copy.deepcopy(item)
                for item in self.objects.values()
                if item.get("object_type_key") == object_type_key
                and str((item.get("properties") or {}).get(property_key)) in values
            ]

        if normalized.startswith("UPDATE ontology_object SET"):
            self.object_updates.append(copy.deepcopy(bound))
            object_id = int(bound["id"])
            current = next(
                (item for item in self.objects.values() if int(item["id"]) == object_id),
                None,
            )
            if current is None:
                raise AssertionError(f"object {object_id} does not exist")
            current.update(
                {
                    "display_name": bound["display_name"],
                    "properties": json.loads(bound["properties"]),
                    "source_properties": json.loads(bound["source_properties"]),
                    "overlay_properties": json.loads(bound["overlay_properties"]),
                    "source_kind": "database",
                    "source_datasource_id": int(bound["datasource_id"]),
                    "status": "active",
                    "version": int(current.get("version") or 1)
                    + int(bound["version_increment"]),
                }
            )
            return []

        if normalized.startswith("UPDATE ontology_object_type SET"):
            return []
        return []

    async def execute_insert(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> int:
        bound = dict(params or {})
        object_id = self.next_id
        self.next_id += 1
        self.inserts.append((sql, copy.deepcopy(bound), object_id))
        if sql.startswith("INSERT INTO ontology_object"):
            item = {
                "id": object_id,
                "domain_id": int(bound["domain_id"]),
                "object_type_id": int(bound["object_type_id"]),
                "primary_value": str(bound["primary_value"]),
                "display_name": bound["display_name"],
                "properties": json.loads(bound["properties"]),
                "source_properties": json.loads(bound["source_properties"]),
                "overlay_properties": json.loads(bound["overlay_properties"]),
                "source_kind": "database",
                "source_datasource_id": int(bound["datasource_id"]),
                "version": 1,
                "status": "active",
            }
            self.objects[(item["object_type_id"], item["primary_value"])] = item
        return object_id

    async def execute_transaction(
        self, statements: list[tuple[str, dict[str, Any]]]
    ) -> None:
        self.transactions.append(copy.deepcopy(statements))


class AllowAllPermissionService:
    async def validate_sql_access(self, agent_id, datasource_id, sql):
        assert agent_id == 7
        assert datasource_id == DATASOURCE_ID
        assert sql.lstrip().upper().startswith("SELECT")
        return True, "OK"

    async def mask_rows(self, agent_id, datasource_id, rows):
        assert agent_id == 7
        assert datasource_id == DATASOURCE_ID
        return rows, {}


def _configure_sync(
    monkeypatch,
    service: OntologyService,
    *,
    source_db: FakeSourceDB,
    management_db: FakeManagementDB,
    object_types: list[dict[str, Any]],
    action_types: list[dict[str, Any]] | None = None,
    link_types: list[dict[str, Any]] | None = None,
) -> None:
    async def require_domain(domain_id: int):
        assert domain_id == DOMAIN_ID
        return {
            "id": DOMAIN_ID,
            "agent_id": 7,
            "datasource_id": DATASOURCE_ID,
        }

    async def datasource_db(datasource_id: int):
        assert datasource_id == DATASOURCE_ID
        return source_db

    async def list_object_types(domain_id: int):
        assert domain_id == DOMAIN_ID
        return copy.deepcopy(object_types)

    async def list_action_types(domain_id: int):
        assert domain_id == DOMAIN_ID
        return copy.deepcopy(action_types or [])

    async def list_link_types(domain_id: int):
        assert domain_id == DOMAIN_ID
        return copy.deepcopy(link_types or [])

    monkeypatch.setattr(service, "_require_domain", require_domain)
    monkeypatch.setattr(service, "list_object_types", list_object_types)
    monkeypatch.setattr(service, "list_action_types", list_action_types)
    monkeypatch.setattr(service, "list_link_types", list_link_types)
    monkeypatch.setattr(ontology_service, "get_datasource_db", datasource_db)
    monkeypatch.setattr(ontology_service, "get_management_db", lambda: management_db)
    monkeypatch.setattr(
        ontology_service,
        "get_permission_service",
        lambda: AllowAllPermissionService(),
    )


@pytest.mark.asyncio
async def test_sync_uses_read_only_select_with_limit_offset_pagination(monkeypatch):
    source_db = FakeSourceDB(
        {"loan_account_indicator": [_loan_row(index) for index in range(1, 6)]}
    )
    management_db = FakeManagementDB()
    service = OntologyService()
    _configure_sync(
        monkeypatch,
        service,
        source_db=source_db,
        management_db=management_db,
        object_types=[_loan_account_type()],
    )

    result = await service.sync_objects_from_datasource(
        DOMAIN_ID,
        page=2,
        page_size=2,
        sync_links=False,
    )

    type_result = result["types"][0]
    assert type_result["total"] == 5
    assert type_result["read"] == 2
    assert type_result["created"] == 2
    assert [item["primary_value"] for item in type_result["objects"]] == ["3", "4"]
    assert len(source_db.queries) == 2
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in source_db.queries)
    count_sql, count_params = source_db.queries[0]
    page_sql, page_params = source_db.queries[1]
    assert "SELECT COUNT(*) AS count FROM (" in count_sql
    assert count_params == {}
    assert "LIMIT :sync_limit OFFSET :sync_offset" in page_sql
    assert page_params == {"sync_limit": 2, "sync_offset": 2}


@pytest.mark.asyncio
async def test_sync_rejects_non_select_source_query_before_business_execution(monkeypatch):
    source_db = FakeSourceDB({"loan_account_indicator": []})
    management_db = FakeManagementDB()
    service = OntologyService()
    object_type = _loan_account_type(source_query="UPDATE loan_account_indicator SET balance = 0")
    _configure_sync(
        monkeypatch,
        service,
        source_db=source_db,
        management_db=management_db,
        object_types=[object_type],
    )

    result = await service.sync_objects_from_datasource(
        DOMAIN_ID,
        sync_links=False,
    )

    assert result["has_errors"] is True
    assert "只允许 SELECT" in result["types"][0]["errors"][0]
    assert source_db.queries == []


@pytest.mark.asyncio
async def test_sync_keeps_action_overlay_over_fresh_source_properties(monkeypatch):
    existing = {
        "id": 77,
        "domain_id": DOMAIN_ID,
        "object_type_id": 11,
        "object_type_key": "LoanAccount",
        "primary_value": "700001",
        "display_name": "LN-700001",
        "properties": {
            "loan_id": 700001,
            "loan_no": "LN-700001",
            "collection_status": "ready",
            "balance": 900.0,
        },
        "source_properties": {
            "loan_id": 700001,
            "loan_no": "LN-700001",
            "collection_status": "not_started",
            "balance": 900.0,
        },
        "overlay_properties": {"collection_status": "ready"},
        "source_kind": "database",
        "source_datasource_id": DATASOURCE_ID,
        "version": 3,
        "status": "active",
    }
    source_db = FakeSourceDB(
        {
            "loan_account_indicator": [
                {
                    "loan_id": 700001,
                    "loan_no": "LN-700001",
                    "collection_status": "not_started",
                    "balance": 1200,
                }
            ]
        }
    )
    management_db = FakeManagementDB([existing])
    service = OntologyService()
    _configure_sync(
        monkeypatch,
        service,
        source_db=source_db,
        management_db=management_db,
        object_types=[_loan_account_type()],
        action_types=[
            {
                "target_object_key": "LoanAccount",
                "effects": [{"property": "collection_status", "value": "ready"}],
            }
        ],
    )

    result = await service.sync_objects_from_datasource(
        DOMAIN_ID,
        sync_links=False,
    )

    synced = result["objects"][0]
    assert synced["source_properties"]["collection_status"] == "not_started"
    assert synced["source_properties"]["balance"] == 1200.0
    assert synced["overlay_properties"] == {"collection_status": "ready"}
    assert synced["properties"]["collection_status"] == "ready"
    assert synced["properties"]["balance"] == 1200.0
    assert synced["version"] == 4
    update = management_db.object_updates[-1]
    assert json.loads(update["source_properties"])["collection_status"] == "not_started"
    assert json.loads(update["overlay_properties"]) == {"collection_status": "ready"}
    assert json.loads(update["properties"])["collection_status"] == "ready"
    assert update["version_increment"] == 1


@pytest.mark.asyncio
async def test_repeated_unchanged_sync_does_not_increment_version(monkeypatch):
    row = {
        "loan_id": 700001,
        "loan_no": "LN-700001",
        "collection_status": "not_started",
        "balance": 900,
    }
    existing = {
        "id": 77,
        "domain_id": DOMAIN_ID,
        "object_type_id": 11,
        "object_type_key": "LoanAccount",
        "primary_value": "700001",
        "display_name": "LN-700001",
        "properties": {**row, "balance": 900.0},
        "source_properties": {**row, "balance": 900.0},
        "overlay_properties": {},
        "source_kind": "database",
        "source_datasource_id": DATASOURCE_ID,
        "version": 5,
        "status": "active",
    }
    source_db = FakeSourceDB({"loan_account_indicator": [row]})
    management_db = FakeManagementDB([existing])
    service = OntologyService()
    _configure_sync(
        monkeypatch,
        service,
        source_db=source_db,
        management_db=management_db,
        object_types=[_loan_account_type()],
    )

    first = await service.sync_objects_from_datasource(DOMAIN_ID, sync_links=False)
    second = await service.sync_objects_from_datasource(DOMAIN_ID, sync_links=False)

    assert first["types"][0]["unchanged"] == 1
    assert second["types"][0]["unchanged"] == 1
    assert first["objects"][0]["version"] == 5
    assert second["objects"][0]["version"] == 5
    assert [item["version_increment"] for item in management_db.object_updates] == [0, 0]


@pytest.mark.asyncio
async def test_sync_requires_domain_datasource(monkeypatch):
    service = OntologyService()

    async def require_domain(_domain_id: int):
        return {"id": DOMAIN_ID, "agent_id": 7, "datasource_id": None}

    async def fail_datasource_lookup(_datasource_id: int):
        raise AssertionError("datasource lookup must not run")

    monkeypatch.setattr(service, "_require_domain", require_domain)
    monkeypatch.setattr(ontology_service, "get_datasource_db", fail_datasource_lookup)

    with pytest.raises(ValueError, match="没有绑定默认数据源"):
        await service.sync_objects_from_datasource(DOMAIN_ID)


@pytest.mark.asyncio
async def test_sync_requires_at_least_one_enabled_object_type(monkeypatch):
    service = OntologyService()

    async def require_domain(_domain_id: int):
        return {"id": DOMAIN_ID, "agent_id": 7, "datasource_id": DATASOURCE_ID}

    async def list_object_types(_domain_id: int):
        return [_loan_account_type(sync_enabled=False)]

    async def fail_datasource_lookup(_datasource_id: int):
        raise AssertionError("datasource lookup must not run")

    monkeypatch.setattr(service, "_require_domain", require_domain)
    monkeypatch.setattr(service, "list_object_types", list_object_types)
    monkeypatch.setattr(ontology_service, "get_datasource_db", fail_datasource_lookup)

    with pytest.raises(ValueError, match="没有启用业务库同步"):
        await service.sync_objects_from_datasource(DOMAIN_ID)


@pytest.mark.asyncio
async def test_sync_rebuilds_relation_from_configured_join_properties(monkeypatch):
    existing_customer = {
        "id": 501,
        "domain_id": DOMAIN_ID,
        "object_type_id": 10,
        "object_type_key": "Customer",
        "object_type_name": "客户",
        "primary_value": "200001",
        "display_name": "张先生",
        "properties": {"customer_id": 200001, "name": "张先生"},
        "source_properties": {"customer_id": 200001, "name": "张先生"},
        "overlay_properties": {},
        "source_kind": "database",
        "source_datasource_id": DATASOURCE_ID,
        "version": 1,
        "status": "active",
    }
    application_type = {
        "id": 20,
        "domain_id": DOMAIN_ID,
        "object_key": "LoanApplication",
        "name": "贷款申请",
        "primary_property": "application_id",
        "display_property": "application_no",
        "sync_enabled": True,
        "source_query": (
            "SELECT application_id, application_no, customer_id "
            "FROM loan_application_indicator ORDER BY application_id"
        ),
        "sync_limit": 100,
        "status": "active",
        "properties": [
            _property("application_id", "integer"),
            _property("application_no"),
            _property("customer_id", "integer"),
        ],
    }
    link_type = {
        "id": 31,
        "link_key": "customer_has_application",
        "source_object_key": "Customer",
        "target_object_key": "LoanApplication",
        "source_property": "customer_id",
        "target_property": "customer_id",
        "status": "active",
    }
    source_db = FakeSourceDB(
        {
            "loan_application_indicator": [
                {
                    "application_id": 900001,
                    "application_no": "APP-900001",
                    "customer_id": 200001,
                }
            ]
        }
    )
    management_db = FakeManagementDB([existing_customer])
    service = OntologyService()
    _configure_sync(
        monkeypatch,
        service,
        source_db=source_db,
        management_db=management_db,
        object_types=[application_type],
        link_types=[link_type],
    )

    result = await service.sync_objects_from_datasource(DOMAIN_ID, sync_links=True)

    assert result["links_synced"] == 1
    assert len(management_db.transactions) == 1
    statements = management_db.transactions[0]
    assert len(statements) == 1
    sql, params = statements[0]
    assert sql.startswith("INSERT INTO ontology_link")
    assert params["link_type_id"] == 31
    assert params["source_object_id"] == 501
    assert params["target_object_id"] == result["objects"][0]["id"]
    assert json.loads(params["properties"]) == {"source": "database_sync"}
