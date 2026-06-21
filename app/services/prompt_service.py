"""Prompt 模板服务 —— 节点提示词的配置化管理与解析。

PromptService 负责 Prompt 模板的 CRUD 和运行时解析。解析逻辑:
1. 按 prompt_key + agent_id + model_config_id + semantic_domain_id 查找最佳模板。
2. 命中多个时,按"非空作用域越多越优先"排序,取最具体的那个。
3. 用模板的 template_text.format(**variables) 渲染变量。
4. 渲染失败(KeyError/ValueError)时自动回退到代码内默认模板,
   避免配置错误直接打断问数链路。

被以下节点调用:意图识别、语义增强、LogicForm 生成、NL2SQL 兜底、
Python 脚本生成、报告生成。
"""

from __future__ import annotations

import logging

from app.db.mysql import get_management_db
from app.models.prompt import PromptTemplateCreate, PromptTemplateUpdate
from app.utils.logging_helpers import json_for_log, truncate_text

logger = logging.getLogger(__name__)


class PromptService:
    """Prompt 模板管理服务 —— 提供模板的增删查改与运行时解析。"""

    async def list(self, prompt_key: str | None = None) -> list[dict]:
        """列出 Prompt 模板,可按 prompt_key 过滤。"""
        db = get_management_db()
        logger.info("prompt list prompt_key=%s", prompt_key)
        if prompt_key:
            rows = await db.execute_query(
                "SELECT * FROM prompt_template WHERE prompt_key = :prompt_key ORDER BY id ASC",
                {"prompt_key": prompt_key},
            )
        else:
            rows = await db.execute_query("SELECT * FROM prompt_template ORDER BY id ASC")
        logger.info("prompt list result prompt_key=%s count=%s", prompt_key, len(rows))
        return rows

    async def upsert(self, template: PromptTemplateCreate) -> int:
        """创建或更新 Prompt 模板。

        若 template.id 已存在则更新,否则按 prompt_key+作用域唯一性去重后插入。
        """
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
        """用提供的字段替换指定 id 的 Prompt 模板。"""
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
        """删除指定 id 的 Prompt 模板。"""
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
        """运行时解析:查找最佳模板并渲染变量,失败时回退到默认模板。

        解析链:
        1. 数据库查最佳模板 → template_text.format(**variables) 渲染
        2. 查找失败 → 用 default_template
        3. 渲染失败(KeyError/ValueError) → 强制用 default_template 渲染

        步骤3保证:即使配置人员漏填了模板变量,也不会打断问数链路,
        而是回退到代码内默认模板继续运行。
        """
        try:
            row = await self.find_best(prompt_key, agent_id, model_config_id, semantic_domain_id)
        except Exception:
            logger.exception("prompt template resolve failed prompt_key=%s", prompt_key)
            row = None

        # 使用数据库模板或默认模板
        template = str(row.get("template_text") if row else default_template)

        try:
            resolved = template.format(**(variables or {}))
        except (KeyError, ValueError):
            # 渲染失败:数据库模板可能包含不完整的 {variable} 占位符
            # 回退到代码内默认模板,避免配置错误打断链路
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
        """查找最匹配的 active 模板。

        匹配逻辑:按 (agent_id, model_config_id, semantic_domain_id) 的非空数量
        加权排序 —— 命中非空作用域越多优先级越高。同一优先级取 id 最大的(最新)。
        这保证了:
        - 全局模板(agent/model/semantic 全 NULL)优先级最低
        - 三者全命中的模板优先级最高
        """
        rows = await get_management_db().execute_query(
            "SELECT * FROM prompt_template WHERE prompt_key = :prompt_key AND status = 'active' "
            # 作用域匹配:NULL 表示"对所有生效"
            "AND (agent_id IS NULL OR agent_id = :agent_id) "
            "AND (model_config_id IS NULL OR model_config_id = :model_config_id) "
            "AND (semantic_domain_id IS NULL OR semantic_domain_id = :semantic_domain_id) "
            # 加权排序:非空作用域越多(加分越高)越优先;同优先级取最新
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


# 全局单例
_prompt_service: PromptService | None = None


def get_prompt_service() -> PromptService:
    """返回进程级 Prompt 服务单例。"""
    global _prompt_service
    if _prompt_service is None:
        _prompt_service = PromptService()
    return _prompt_service
