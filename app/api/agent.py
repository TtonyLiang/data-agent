"""智能体管理 API —— 智能体的增删改查与关联管理。

智能体是问数链路的运行入口。创建时可一次性绑定数据源。
删除时会级联删除关联的语义层、资产、会话历史等。
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, require_admin
from app.db.mysql import get_management_db
from app.models.agent import AgentCreate
from app.models.user import PublicUser
from app.services.datasource_service import get_datasource_service
from app.services.user_service import get_user_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/create", dependencies=[Depends(require_admin)])
async def create_agent(agent: AgentCreate):
    """创建智能体,可选一次性绑定数据源。"""
    db = get_management_db()
    agent_id = await db.execute_insert(
        "INSERT INTO agent "
        "(name, description, chat_model_config_id, embedding_model_config_id, "
        "semantic_domain_id, default_questions, llm_provider, llm_model) "
        "VALUES (:name, :desc, :chat_model_config_id, :embedding_model_config_id, "
        ":semantic_domain_id, :default_questions, :provider, :model)",
        {
            "name": agent.name,
            "desc": agent.description,
            "chat_model_config_id": agent.chat_model_config_id,
            "embedding_model_config_id": agent.embedding_model_config_id,
            "semantic_domain_id": agent.semantic_domain_id,
            "default_questions": json.dumps(normalize_default_questions(agent.default_questions), ensure_ascii=False),
            "provider": agent.llm_provider,
            "model": agent.llm_model,
        },
    )
    if agent.datasource_ids:
        await get_datasource_service().set_agent_datasources(agent_id, agent.datasource_ids)
    logger.info("agent create id=%s name=%s", agent_id, agent.name)
    return {"id": agent_id, "message": "智能体创建成功"}


@router.get("/list")
async def list_agents(current_user: PublicUser = Depends(get_current_user)):
    """列出所有智能体(含绑定的模型配置和语义层名称)。"""
    db = get_management_db()
    if current_user.role == "admin":
        rows = await db.execute_query(_agent_select_sql("ORDER BY a.id DESC"))
    else:
        rows = await db.execute_query(
            _agent_select_sql(
                "JOIN user_agent_permission uap ON uap.agent_id = a.id "
                "WHERE uap.user_id = :user_id ORDER BY a.id DESC"
            ),
            {"user_id": current_user.id},
        )
    return {"agents": [_public_agent(row) for row in rows]}


@router.put("/{agent_id}", dependencies=[Depends(require_admin)])
async def update_agent(agent_id: int, agent: AgentCreate):
    """更新智能体配置。"""
    db = get_management_db()
    await db.execute_query(
        "UPDATE agent SET name = :name, description = :desc, "
        "chat_model_config_id = :chat_model_config_id, "
        "embedding_model_config_id = :embedding_model_config_id, "
        "semantic_domain_id = :semantic_domain_id, "
        "default_questions = :default_questions, "
        "llm_provider = :provider, llm_model = :model WHERE id = :id",
        {
            "id": agent_id,
            "name": agent.name,
            "desc": agent.description,
            "chat_model_config_id": agent.chat_model_config_id,
            "embedding_model_config_id": agent.embedding_model_config_id,
            "semantic_domain_id": agent.semantic_domain_id,
            "default_questions": json.dumps(normalize_default_questions(agent.default_questions), ensure_ascii=False),
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
async def get_agent(agent_id: int, current_user: PublicUser = Depends(get_current_user)):
    """获取单个智能体详情。"""
    if not await get_user_service().can_access_agent(current_user, agent_id):
        raise HTTPException(status_code=403, detail="无权访问该智能体")
    db = get_management_db()
    rows = await db.execute_query(
        _agent_select_sql("WHERE a.id = :id"),
        {"id": agent_id},
    )
    if not rows:
        return {"error": "智能体不存在"}
    return {"agent": _public_agent(rows[0])}


@router.delete("/{agent_id}", dependencies=[Depends(require_admin)])
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
    public = {key: value for key, value in row.items() if key != "api_key"}
    public["default_questions"] = normalize_default_questions(public.get("default_questions"))
    return public


def normalize_default_questions(value) -> list[str]:
    """归一化智能体默认推荐问题,支持 DB JSON 字符串和前端数组。"""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]
    if not isinstance(value, list):
        return []
    questions: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        questions.append(text)
        seen.add(text)
    return questions[:12]


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
