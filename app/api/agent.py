from fastapi import APIRouter

from app.models.agent import AgentCreate
from app.db.mysql import get_management_db

router = APIRouter()


@router.post("/create")
async def create_agent(agent: AgentCreate):
    db = get_management_db()
    await db.execute_query(
        "INSERT INTO agent (name, description, llm_provider, llm_model) "
        "VALUES (:name, :desc, :provider, :model)",
        {
            "name": agent.name,
            "desc": agent.description,
            "provider": agent.llm_provider,
            "model": agent.llm_model,
        },
    )
    row = await db.execute_query(
        "SELECT id FROM agent ORDER BY id DESC LIMIT 1"
    )
    return {"id": row[0]["id"], "message": "智能体创建成功"}


@router.get("/list")
async def list_agents():
    db = get_management_db()
    rows = await db.execute_query("SELECT * FROM agent ORDER BY id DESC")
    return {"agents": rows}


@router.get("/{agent_id}")
async def get_agent(agent_id: int):
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT * FROM agent WHERE id = :id", {"id": agent_id}
    )
    if not rows:
        return {"error": "智能体不存在"}
    return {"agent": rows[0]}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: int):
    db = get_management_db()
    await db.execute_query("DELETE FROM agent WHERE id = :id", {"id": agent_id})
    return {"message": "删除成功"}
