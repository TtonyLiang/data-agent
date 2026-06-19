from __future__ import annotations

import logging

from app.db.mysql import get_management_db
from app.models.prompt import PromptTemplateCreate, PromptTemplateUpdate
from app.utils.logging_helpers import json_for_log, truncate_text

logger = logging.getLogger(__name__)


class PromptService:
    async def list(self, prompt_key: str | None = None) -> list[dict]:
        """List prompt templates, optionally scoped to a single prompt key."""
        db = get_management_db()
        logger.info("prompt list prompt_key=%s", prompt_key)
        if prompt_key:
            rows = await db.execute_query(
                "SELECT * FROM prompt_template WHERE prompt_key = :prompt_key ORDER BY id ASC",
                {"prompt_key": prompt_key},
            )
        else:
            rows = await db.execute_query(
                "SELECT * FROM prompt_template ORDER BY prompt_key, id ASC"
            )
        logger.info("prompt list result prompt_key=%s count=%s", prompt_key, len(rows))
        return rows

    async def upsert(self, template: PromptTemplateCreate) -> int:
        """Create a prompt template or update the existing id carried by the payload."""
        db = get_management_db()
        logger.info(
            "prompt upsert prompt_key=%s id=%s scope=%s",
            template.prompt_key,
            template.id,
            json_for_log(
                {
                    "agent_id": template.agent_id,
                    "model_config_id": template.model_config_id,
                    "semantic_domain_id": template.semantic_domain_id,
                    "status": template.status,
                }
            ),
        )
        if template.id:
            await self.update(
                template.id, PromptTemplateUpdate(**template.model_dump(exclude={"id"}))
            )
            return template.id
        return await db.execute_insert(
            "INSERT INTO prompt_template "
            "(prompt_key, name, description, agent_id, model_config_id, "
            "semantic_domain_id, template_text, status) "
            "VALUES (:prompt_key, :name, :description, :agent_id, :model_config_id, "
            ":semantic_domain_id, :template_text, :status)",
            template.model_dump(exclude={"id"}),
        )

    async def update(self, template_id: int, template: PromptTemplateUpdate) -> bool:
        """Replace one prompt template row with the supplied editable fields."""
        db = get_management_db()
        logger.info(
            "prompt update id=%s prompt_key=%s template_chars=%s",
            template_id,
            template.prompt_key,
            len(template.template_text or ""),
        )
        await db.execute_query(
            "UPDATE prompt_template SET prompt_key = :prompt_key, name = :name, "
            "description = :description, "
            "agent_id = :agent_id, model_config_id = :model_config_id, "
            "semantic_domain_id = :semantic_domain_id, "
            "template_text = :template_text, status = :status WHERE id = :id",
            {**template.model_dump(), "id": template_id},
        )
        return True

    async def delete(self, template_id: int) -> bool:
        """Delete a prompt template by id."""
        logger.info("prompt delete id=%s", template_id)
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
        """Resolve the best active template for a scope and format it with variables."""
        try:
            row = await self.find_best(prompt_key, agent_id, model_config_id, semantic_domain_id)
        except Exception:
            logger.exception("prompt template resolve failed prompt_key=%s", prompt_key)
            row = None
        template = str(row.get("template_text") if row else default_template)
        try:
            resolved = template.format(**(variables or {}))
        except (KeyError, ValueError):
            logger.exception(
                "prompt template format failed prompt_key=%s template_id=%s "
                "variables=%s, fallback to default",
                prompt_key,
                row.get("id") if row else None,
                json_for_log(variables or {}, text_limit=600),
            )
            resolved = default_template.format(**(variables or {}))
        logger.info(
            "prompt resolved prompt_key=%s source=%s template_id=%s scope=%s chars=%s preview=%s",
            prompt_key,
            "database" if row else "default",
            row.get("id") if row else None,
            json_for_log(
                {
                    "agent_id": agent_id,
                    "model_config_id": model_config_id,
                    "semantic_domain_id": semantic_domain_id,
                }
            ),
            len(resolved),
            truncate_text(resolved, 600),
        )
        return resolved

    async def find_best(
        self,
        prompt_key: str,
        agent_id: int | None,
        model_config_id: int | None,
        semantic_domain_id: int | None,
    ) -> dict | None:
        """Find the most specific active template matching agent, model, and semantic domain."""
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
        logger.info(
            "prompt find_best prompt_key=%s agent_id=%s model_config_id=%s "
            "semantic_domain_id=%s matched=%s",
            prompt_key,
            agent_id,
            model_config_id,
            semantic_domain_id,
            rows[0]["id"] if rows else None,
        )
        return rows[0] if rows else None


_prompt_service: PromptService | None = None


def get_prompt_service() -> PromptService:
    """Return the process-wide prompt service singleton."""
    global _prompt_service
    if _prompt_service is None:
        _prompt_service = PromptService()
    return _prompt_service
