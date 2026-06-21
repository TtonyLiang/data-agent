"""智能体管理 API —— 智能体的增删改查与关联管理。

智能体是问数链路的运行入口。创建时可一次性绑定数据源。
删除时会级联删除关联的语义层、资产、会话历史等。
"""

import logging

from fastapi import APIRouter, HTTPException

from app.db.mysql import get_management_db
from app.models.agent import AgentCreate
from app.services.datasource_service import get_datasource_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/create")
async def create_agent(agent: AgentCreate):
    """创建智能体,可选一次性绑定数据源。"""
    db = get_management_db()
    agent_id = await db.execute_insert(
        "INSERT INTO agent "
        "(name, description, chat_model_config_id, embedding_model_config_id, "
        "semantic_domain_id, llm_provider, llm_model) "
        "VALUES (:name, :desc, :chat_model_config_id, :embedding_model_config_id, "
        ":semantic_domain_id, :provider, :model)",
        {
            "name": agent.name,
            "desc": agent.description,
            "chat_model_config_id": agent.chat_model_config_id,
            "embedding_model_config_id": agent.embedding_model_config_id,
            "semantic_domain_id": agent.semantic_domain_id,
            "provider": agent.llm_provider,
            "model": agent.llm_model,
        },
    )
    if agent.datasource_ids:
        await get_datasource_service().set_agent_datasources(agent_id, agent.datasource_ids)
    logger.info("agent create id=%s name=%s", agent_id, agent.name)
    return {"id": agent_id, "message": "智能体创建成功"}


@router.get("/list")
async def list_agents():
    """列出所有智能体(含绑定的模型配置和语义层名称)。"""
    db = get_management_db()
    rows = await db.execute_query(_agent_select_sql("ORDER BY a.id DESC"))
    return {"agents": [_public_agent(row) for row in rows]}


@router.put("/{agent_id}")
async def update_agent(agent_id: int, agent: AgentCreate):
    """更新智能体配置。"""
    db = get_management_db()
    await db.execute_query(
        "UPDATE agent SET name = :name, description = :desc, "
        "chat_model_config_id = :chat_model_config_id, "
        "embedding_model_config_id = :embedding_model_config_id, "
        "semantic_domain_id = :semantic_domain_id, "
        "llm_provider = :provider, llm_model = :model WHERE id = :id",
        {
            "id": agent_id,
            "name": agent.name,
            "desc": agent.description,
            "chat_model_config_id": agent.chat_model_config_id,
            "embedding_model_config_id": agent.embedding_model_config_id,
            "semantic_domain_id": agent.semantic_domain_id,
            "provider": agent.llm_provider,
            "model": agent.llm_model,
        },
    )
    await get_datasource_service().set_agent_datasources(agent_id, agent.datasource_ids)
    rows = await db.execute_query(
        _agent_select_sql("WHERE a.id = :id"),
        {"id": agent_id},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="智能体不存在")
    return {"agent": _public_agent(rows[0]), "message": "更新成功"}


@router.get("/{agent_id}")
async def get_agent(agent_id: int):
    """获取单个智能体详情。"""
    db = get_management_db()
    rows = await db.execute_query(
        _agent_select_sql("WHERE a.id = :id"),
        {"id": agent_id},
    )
    if not rows:
        return {"error": "智能体不存在"}
    return {"agent": _public_agent(rows[0])}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: int):
    """删除智能体及其关联的全部语义层资产、会话历史等。

    级联删除顺序(先删子表再删主表):
    语义资产 → 语义领域 → 数据源绑定 → 知识文档 → 会话历史 → 智能体本身
    """
    db = get_management_db()

    # 第1步:删除语义资产(通过 semantic_domain 关联)
    for table in (
        "logic_form_template",
        "semantic_mapping",
        "semantic_rule",
        "semantic_metric",
        "semantic_relation",
        "semantic_concept",
    ):
        await db.execute_query(
            f"DELETE FROM {table} WHERE domain_id IN "
            "(SELECT id FROM semantic_domain WHERE agent_id = :id)",
            {"id": agent_id},
        )
    # 第2步:删除语义领域、绑定、知识文档、会话历史、智能体本身
    await db.execute_query("DELETE FROM semantic_domain WHERE agent_id = :id", {"id": agent_id})
    await db.execute_query("DELETE FROM agent_datasource WHERE agent_id = :id", {"id": agent_id})
    await db.execute_query("DELETE FROM agent_knowledge WHERE agent_id = :id", {"id": agent_id})
    await db.execute_query("DELETE FROM chat_history WHERE agent_id = :id", {"id": agent_id})
    await db.execute_query("DELETE FROM agent WHERE id = :id", {"id": agent_id})

    logger.info("agent delete id=%s cascading_complete", agent_id)
    return {"message": "删除成功"}


def _public_agent(row: dict) -> dict:
    """把数据库行转为 API 出参(去掉 api_key 明文)。"""
    return {key: value for key, value in row.items() if key != "api_key"}


def _agent_select_sql(suffix: str = "") -> str:
    """智能体查询 SQL(含 JOIN 模型配置和语义层名称)。"""
    return (
        "SELECT a.*, chat.name AS chat_model_config_name, "
        "emb.name AS embedding_model_config_name, "
        "sd.name AS semantic_domain_name, sd.domain_key AS semantic_domain_key "
        "FROM agent a "
        "LEFT JOIN model_config chat ON chat.id = a.chat_model_config_id "
        "LEFT JOIN model_config emb ON emb.id = a.embedding_model_config_id "
        "LEFT JOIN semantic_domain sd ON sd.id = a.semantic_domain_id "
        f"{suffix}"
    )
