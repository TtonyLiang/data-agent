import pytest

from app.agent.prompts import default_prompt_templates
from app.api.prompt import list_prompt_catalog
from app.db import migrations


def test_default_prompt_catalog_exposes_agent_prompt_files():
    prompts = default_prompt_templates()
    keys = {item["prompt_key"] for item in prompts}

    assert "intent_recognition.system" in keys
    assert "semantic_enhance.system" in keys
    assert "nl2lf_generate.system" in keys
    assert "nl2sql_fallback.system" in keys
    assert "phase3_python_generate.system" in keys
    assert "phase3_python_generate.user" in keys
    assert "phase3_report_generator.system" in keys
    assert "phase3_report_generator.user" in keys
    assert all(item["template_text"].strip() for item in prompts)
    assert all("语义层" not in item["description"] for item in prompts)


@pytest.mark.asyncio
async def test_prompt_catalog_exposes_agent_scope_policy():
    catalog = (await list_prompt_catalog())["prompts"]
    by_key = {item["prompt_key"]: item for item in catalog}

    assert by_key["semantic_enhance.system"]["scope_policy"] == "business_semantics"
    assert by_key["semantic_enhance.system"]["agent_scope_allowed"] is False
    assert by_key["nl2lf_generate.system"]["agent_scope_allowed"] is False
    assert by_key["nl2sql_fallback.system"]["agent_scope_allowed"] is False
    assert by_key["phase3_report_generator.system"]["scope_policy"] == (
        "interaction_or_output"
    )
    assert by_key["phase3_report_generator.system"]["agent_scope_allowed"] is True


@pytest.mark.asyncio
async def test_seed_default_prompt_templates_only_inserts_missing_global_templates(monkeypatch):
    existing_key = "semantic_enhance.system"

    class FakeDB:
        def __init__(self):
            self.inserted = []
            self.queries = []

        async def execute_scalar(self, sql: str, params: dict | None = None):
            return 1 if params and params["prompt_key"] == existing_key else 0

        async def execute_query(self, sql: str, params: dict | None = None):
            self.queries.append((sql, params or {}))
            return []

        async def execute_transaction(self, statements):
            self.inserted.extend(statements)

    db = FakeDB()
    monkeypatch.setattr(migrations, "get_management_db", lambda: db)

    await migrations.seed_default_prompt_templates()

    inserted_keys = [params["prompt_key"] for _, params in db.inserted]
    assert existing_key not in inserted_keys
    assert "nl2lf_generate.system" in inserted_keys
    assert "phase3_report_generator.user" in inserted_keys
    assert any("REPLACE(description" in sql for sql, _ in db.queries)
    assert any(
        "template_text = :template_text" in sql
        and params.get("prompt_key") == "nl2lf_generate.system"
        for sql, params in db.queries
    )
