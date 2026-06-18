from __future__ import annotations

import logging

from app.db.mysql import get_management_db
from app.models.prompt import PromptTemplateCreate, PromptTemplateUpdate

logger = logging.getLogger(__name__)


class PromptService:
    async def list(self, prompt_key: str | None = None) -> list[dict]:
        db = get_management_db()
        if prompt_key:
            return await db.execute_query(
                "SELECT * FROM prompt_template WHERE prompt_key = :prompt_key ORDER BY id ASC",
                {"prompt_key": prompt_key},
            )
        return await db.execute_query("SELECT * FROM prompt_template ORDER BY prompt_key, id ASC")

    async def upsert(self, template: PromptTemplateCreate) -> int:
        db = get_management_db()
        if template.id:
            await self.update(template.id, PromptTemplateUpdate(**template.model_dump(exclude={"id"})))
            return template.id
        return await db.execute_insert(
            "INSERT INTO prompt_template "
            "(prompt_key, name, description, agent_id, model_config_id, semantic_domain_id, template_text, status) "
            "VALUES (:prompt_key, :name, :description, :agent_id, :model_config_id, :semantic_domain_id, :template_text, :status)",
            template.model_dump(exclude={"id"}),
        )

    async def update(self, template_id: int, template: PromptTemplateUpdate) -> bool:
        db = get_management_db()
        await db.execute_query(
            "UPDATE prompt_template SET prompt_key = :prompt_key, name = :name, description = :description, "
            "agent_id = :agent_id, model_config_id = :model_config_id, semantic_domain_id = :semantic_domain_id, "
            "template_text = :template_text, status = :status WHERE id = :id",
            {**template.model_dump(), "id": template_id},
        )
        return True

    async def delete(self, template_id: int) -> bool:
        await get_management_db().execute_query(
            "DELETE FROM prompt_template WHERE id = :id",
            {"id": template_id},
        )
        return True

    async def resolve(
        self,
        prompt_key: str,
        default_template: str,
        *,
        agent_id: int | None = None,
        model_config_id: int | None = None,
        semantic_domain_id: int | None = None,
        variables: dict | None = None,
    ) -> str:
        try:
            row = await self.find_best(prompt_key, agent_id, model_config_id, semantic_domain_id)
        except Exception:
            logger.exception("prompt template resolve failed prompt_key=%s", prompt_key)
            row = None
        template = str(row.get("template_text") if row else default_template)
        try:
            return template.format(**(variables or {}))
        except (KeyError, ValueError):
            return default_template.format(**(variables or {}))

    async def find_best(
        self,
        prompt_key: str,
        agent_id: int | None,
        model_config_id: int | None,
        semantic_domain_id: int | None,
    ) -> dict | None:
        rows = await get_management_db().execute_query(
            "SELECT * FROM prompt_template WHERE prompt_key = :prompt_key AND status = 'active' "
            "AND (agent_id IS NULL OR agent_id = :agent_id) "
            "AND (model_config_id IS NULL OR model_config_id = :model_config_id) "
            "AND (semantic_domain_id IS NULL OR semantic_domain_id = :semantic_domain_id) "
            "ORDER BY "
            "CASE WHEN agent_id IS NULL THEN 0 ELSE 4 END + "
            "CASE WHEN model_config_id IS NULL THEN 0 ELSE 2 END + "
            "CASE WHEN semantic_domain_id IS NULL THEN 0 ELSE 1 END DESC, id DESC "
            "LIMIT 1",
            {
                "prompt_key": prompt_key,
                "agent_id": agent_id,
                "model_config_id": model_config_id,
                "semantic_domain_id": semantic_domain_id,
            },
        )
        return rows[0] if rows else None


_prompt_service: PromptService | None = None


def get_prompt_service() -> PromptService:
    global _prompt_service
    if _prompt_service is None:
        _prompt_service = PromptService()
    return _prompt_service
