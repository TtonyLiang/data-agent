from fastapi import APIRouter, HTTPException

from app.models.agent import AgentCreate
from app.db.mysql import get_management_db
from app.services.datasource_service import get_datasource_service

router = APIRouter()


@router.post("/create")
async def create_agent(agent: AgentCreate):
    db = get_management_db()
    agent_id = await db.execute_insert(
        "INSERT INTO agent "
        "(name, description, chat_model_config_id, embedding_model_config_id, semantic_domain_id, llm_provider, llm_model) "
        "VALUES (:name, :desc, :chat_model_config_id, :embedding_model_config_id, :semantic_domain_id, :provider, :model)",
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
    return {"id": agent_id, "message": "智能体创建成功"}


@router.get("/list")
async def list_agents():
    db = get_management_db()
    rows = await db.execute_query(_agent_select_sql("ORDER BY a.id DESC"))
    return {"agents": [_public_agent(row) for row in rows]}


@router.put("/{agent_id}")
async def update_agent(agent_id: int, agent: AgentCreate):
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
    db = get_management_db()
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
    await db.execute_query("DELETE FROM semantic_domain WHERE agent_id = :id", {"id": agent_id})
    await db.execute_query("DELETE FROM agent_datasource WHERE agent_id = :id", {"id": agent_id})
    await db.execute_query("DELETE FROM agent_knowledge WHERE agent_id = :id", {"id": agent_id})
    await db.execute_query("DELETE FROM chat_history WHERE agent_id = :id", {"id": agent_id})
    await db.execute_query("DELETE FROM agent WHERE id = :id", {"id": agent_id})
    return {"message": "删除成功"}


def _public_agent(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "api_key"}


def _agent_select_sql(suffix: str = "") -> str:
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
