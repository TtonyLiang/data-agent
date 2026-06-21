import pytest

from app.api import system_parameter as system_parameter_api
from app.models.system_parameter import SystemParameterUpdate
from app.services.system_parameter_service import SystemParameterService


class FakeParamDB:
    def __init__(self):
        self.rows = {
            "schema_recall.max_tables": {
                "param_key": "schema_recall.max_tables",
                "name": "最多表数",
                "value_json": "6",
                "value_type": "int",
                "category": "schema_recall",
                "description": "",
                "created_at": None,
                "updated_at": None,
            },
            "schema_recall.required_score_ratio": {
                "param_key": "schema_recall.required_score_ratio",
                "name": "必须召回阈值",
                "value_json": "0.35",
                "value_type": "float",
                "category": "schema_recall",
                "description": "",
                "created_at": None,
                "updated_at": None,
            },
            "schema_recall.optional_score_ratio": {
                "param_key": "schema_recall.optional_score_ratio",
                "name": "可召回阈值",
                "value_json": "0.15",
                "value_type": "float",
                "category": "schema_recall",
                "description": "",
                "created_at": None,
                "updated_at": None,
            },
        }

    async def execute_query(self, sql: str, params: dict | None = None):
        return list(self.rows.values())

    async def execute_transaction(self, statements):
        for _sql, params in statements:
            self.rows[params["key"]]["value_json"] = params["value_json"]


@pytest.mark.asyncio
async def test_system_parameter_service_updates_schema_recall_settings(monkeypatch):
    db = FakeParamDB()
    monkeypatch.setattr("app.services.system_parameter_service.get_management_db", lambda: db)
    service = SystemParameterService()

    settings = await service.get_schema_recall_settings()
    assert settings.max_tables == 6
    assert settings.required_score_ratio == 0.35
    assert settings.optional_score_ratio == 0.15

    await service.update_many(
        [
            SystemParameterUpdate(key="schema_recall.max_tables", value=3),
            SystemParameterUpdate(key="schema_recall.required_score_ratio", value=0.4),
            SystemParameterUpdate(key="schema_recall.optional_score_ratio", value=0.2),
        ]
    )
    updated = await service.get_schema_recall_settings()

    assert updated.max_tables == 3
    assert updated.required_score_ratio == 0.4
    assert updated.optional_score_ratio == 0.2


@pytest.mark.asyncio
async def test_system_parameter_api_lists_parameters(monkeypatch):
    class FakeService:
        async def list(self, category=None):
            return [{"key": "schema_recall.max_tables", "category": category or "schema_recall"}]

    monkeypatch.setattr(
        system_parameter_api,
        "get_system_parameter_service",
        lambda: FakeService(),
    )

    response = await system_parameter_api.list_system_parameters(category="schema_recall")

    assert response["parameters"][0]["key"] == "schema_recall.max_tables"
