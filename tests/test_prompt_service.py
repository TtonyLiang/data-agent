import pytest

from app.services import prompt_service
from app.services.prompt_service import PromptService


class FakePromptDB:
    async def execute_query(self, sql: str, params: dict | None = None):
        if "FROM prompt_template" in sql:
            return [
                {
                    "id": 2,
                    "prompt_key": params["prompt_key"],
                    "template_text": "智能体模板 {runtime_context}",
                }
            ]
        return []

    async def execute_insert(self, sql: str, params: dict | None = None):
        return 9


@pytest.mark.asyncio
async def test_prompt_service_resolves_active_template_with_variables(monkeypatch):
    monkeypatch.setattr(prompt_service, "get_management_db", lambda: FakePromptDB())

    resolved = await PromptService().resolve(
        "nl2lf_generate.system",
        "默认 {runtime_context}",
        agent_id=1,
        semantic_domain_id=2,
        variables={"runtime_context": "贷款风控"},
    )

    assert resolved == "智能体模板 贷款风控"


@pytest.mark.asyncio
async def test_prompt_service_falls_back_when_template_variable_is_invalid(monkeypatch):
    class BadTemplateDB(FakePromptDB):
        async def execute_query(self, sql: str, params: dict | None = None):
            return [{"template_text": "坏模板 {missing}"}]

    monkeypatch.setattr(prompt_service, "get_management_db", lambda: BadTemplateDB())

    resolved = await PromptService().resolve(
        "nl2lf_generate.system",
        "默认 {runtime_context}",
        variables={"runtime_context": "贷款风控"},
    )

    assert resolved == "默认 贷款风控"


@pytest.mark.asyncio
async def test_prompt_service_list_orders_all_templates_by_id(monkeypatch):
    class ListPromptDB:
        def __init__(self):
            self.queries = []

        async def execute_query(self, sql: str, params: dict | None = None):
            self.queries.append((sql, params))
            return []

    db = ListPromptDB()
    monkeypatch.setattr(prompt_service, "get_management_db", lambda: db)

    await PromptService().list()

    assert "ORDER BY id ASC" in db.queries[0][0]
    assert "ORDER BY prompt_key" not in db.queries[0][0]
