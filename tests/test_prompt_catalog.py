import pytest

from app.agent.prompts import default_prompt_templates
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


@pytest.mark.asyncio
async def test_seed_default_prompt_templates_only_inserts_missing_global_templates(monkeypatch):
    existing_key = "semantic_enhance.system"

    class FakeDB:
        def __init__(self):
            self.inserted = []

        async def execute_scalar(self, sql: str, params: dict | None = None):
            return 1 if params and params["prompt_key"] == existing_key else 0

        async def execute_transaction(self, statements):
            self.inserted.extend(statements)

    db = FakeDB()
    monkeypatch.setattr(migrations, "get_management_db", lambda: db)

    await migrations.seed_default_prompt_templates()

    inserted_keys = [params["prompt_key"] for _, params in db.inserted]
    assert existing_key not in inserted_keys
    assert "nl2lf_generate.system" in inserted_keys
    assert "phase3_report_generator.user" in inserted_keys
