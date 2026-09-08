from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import prompt as prompt_api
from app.models.prompt import PromptTemplateCreate, prompt_allows_agent_scope
from app.services import prompt_service
from app.services.prompt_service import PromptService


class FakePromptDB:
    def __init__(self):
        self.queries = []
        self.inserts = []

    async def execute_query(self, sql: str, params: dict | None = None):
        self.queries.append((sql, params or {}))
        if "FROM prompt_template" in sql:
            return [
                {
                    "id": 2,
                    "prompt_key": params["prompt_key"],
                    "template_text": "作用域模板 {runtime_context}",
                }
            ]
        return []

    async def execute_insert(self, sql: str, params: dict | None = None):
        self.inserts.append((sql, params or {}))
        return 9


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt_key",
    [
        "semantic_enhance.system",
        "nl2lf_generate.system",
        "nl2sql_fallback.system",
        "phase3_python_generate.system",
        "phase3_python_generate.user",
    ],
)
async def test_business_semantic_prompt_ignores_agent_scope(monkeypatch, prompt_key):
    db = FakePromptDB()
    monkeypatch.setattr(prompt_service, "get_management_db", lambda: db)

    resolved = await PromptService().resolve(
        prompt_key,
        "默认 {runtime_context}",
        agent_id=1,
        semantic_domain_id=2,
        variables={"runtime_context": "贷款风控"},
    )

    assert resolved == "作用域模板 贷款风控"
    assert db.queries[0][1]["agent_id"] is None
    assert db.queries[0][1]["semantic_domain_id"] == 2


@pytest.mark.asyncio
async def test_output_prompt_keeps_agent_scope(monkeypatch):
    db = FakePromptDB()
    monkeypatch.setattr(prompt_service, "get_management_db", lambda: db)

    resolved = await PromptService().resolve(
        "phase3_report_generator.system",
        "默认 {runtime_context}",
        agent_id=7,
        semantic_domain_id=2,
        variables={"runtime_context": "贷款风控"},
    )

    assert resolved == "作用域模板 贷款风控"
    assert db.queries[0][1]["agent_id"] == 7


@pytest.mark.asyncio
async def test_business_semantic_prompt_rejects_new_agent_override(monkeypatch):
    db = FakePromptDB()
    monkeypatch.setattr(prompt_service, "get_management_db", lambda: db)

    with pytest.raises(ValueError, match="业务语义关键 Prompt"):
        await PromptService().upsert(
            PromptTemplateCreate(
                prompt_key="nl2lf_generate.system",
                name="非法智能体覆盖",
                agent_id=7,
                semantic_domain_id=2,
                template_text="template",
            )
        )

    assert db.inserts == []


@pytest.mark.asyncio
async def test_prompt_api_maps_invalid_agent_scope_to_bad_request(monkeypatch):
    service = AsyncMock()
    service.upsert.side_effect = ValueError("业务语义关键 Prompt 不允许按验证智能体覆盖")
    monkeypatch.setattr(prompt_api, "get_prompt_service", lambda: service)

    with pytest.raises(HTTPException) as exc_info:
        await prompt_api.upsert_prompt_template(
            PromptTemplateCreate(
                prompt_key="semantic_enhance.system",
                name="非法智能体覆盖",
                agent_id=7,
                template_text="template",
            )
        )

    assert exc_info.value.status_code == 400
    assert "业务语义关键 Prompt" in str(exc_info.value.detail)


def test_prompt_scope_policy_keeps_only_business_logic_agent_independent():
    assert not prompt_allows_agent_scope("semantic_enhance.system")
    assert not prompt_allows_agent_scope("nl2lf_generate.system")
    assert not prompt_allows_agent_scope("nl2sql_fallback.system")
    assert not prompt_allows_agent_scope("phase3_python_generate.system")
    assert prompt_allows_agent_scope("phase3_report_generator.system")
    assert not prompt_allows_agent_scope("intent_recognition.system")
    assert not prompt_allows_agent_scope("unknown_future_prompt.system")


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
