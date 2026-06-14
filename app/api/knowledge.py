from fastapi import APIRouter

from app.models.knowledge import SemanticModel, BusinessKnowledge
from app.db.mysql import get_management_db
from app.services.embedding_service import get_embedding_service
from app.services.vector_store import get_vector_store, VectorRecord

router = APIRouter()


@router.post("/semantic-model")
async def create_semantic_model(sm: SemanticModel):
    db = get_management_db()
    await db.execute_query(
        "INSERT INTO semantic_model (agent_id, table_name, column_name, business_name, synonyms, description, data_type) "
        "VALUES (:aid, :tn, :cn, :bn, :syn, :desc, :dt)",
        {
            "aid": sm.agent_id, "tn": sm.table_name, "cn": sm.column_name,
            "bn": sm.business_name, "syn": sm.synonyms, "desc": sm.description,
            "dt": sm.data_type,
        },
    )
    # 获取插入的 ID
    row = await db.execute_query(
        "SELECT id FROM semantic_model WHERE agent_id = :aid ORDER BY id DESC LIMIT 1",
        {"aid": sm.agent_id},
    )
    record_id = row[0]["id"] if row else 0

    # 同步到 Milvus
    await _index_semantic_model(sm, record_id)

    return {"id": record_id, "message": "语义模型创建成功"}


@router.get("/semantic-model/{agent_id}")
async def list_semantic_models(agent_id: int):
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT * FROM semantic_model WHERE agent_id = :aid", {"aid": agent_id}
    )
    return {"models": rows}


@router.post("/business-knowledge")
async def create_business_knowledge(bk: BusinessKnowledge):
    db = get_management_db()
    await db.execute_query(
        "INSERT INTO business_knowledge (agent_id, title, content, knowledge_type, synonyms, is_recall) "
        "VALUES (:aid, :title, :content, :ktype, :syn, :recall)",
        {
            "aid": bk.agent_id, "title": bk.title, "content": bk.content,
            "ktype": bk.knowledge_type, "syn": bk.synonyms, "recall": 1 if bk.is_recall else 0,
        },
    )
    row = await db.execute_query(
        "SELECT id FROM business_knowledge WHERE agent_id = :aid ORDER BY id DESC LIMIT 1",
        {"aid": bk.agent_id},
    )
    record_id = row[0]["id"] if row else 0

    # 同步到 Milvus
    await _index_business_knowledge(bk, record_id)

    return {"id": record_id, "message": "业务知识创建成功"}


@router.get("/business-knowledge/{agent_id}")
async def list_business_knowledge(agent_id: int):
    db = get_management_db()
    rows = await db.execute_query(
        "SELECT * FROM business_knowledge WHERE agent_id = :aid", {"aid": agent_id}
    )
    return {"knowledge": rows}


@router.post("/sync/{agent_id}")
async def sync_knowledge_to_vector(agent_id: int):
    """批量同步某个 agent 的所有知识到 Milvus (全量重建)."""
    db = get_management_db()
    emb_svc = get_embedding_service()
    vec_store = get_vector_store()

    # 清空旧向量
    vec_store.delete_collection(agent_id)

    records = []

    # 语义模型
    sm_rows = await db.execute_query(
        "SELECT * FROM semantic_model WHERE agent_id = :aid", {"aid": agent_id}
    )
    for sm in sm_rows:
        text = f"{sm['business_name']}"
        if sm.get("synonyms"):
            text += f" 同义词: {sm['synonyms']}"
        if sm.get("description"):
            text += f" {sm['description']}"
        text += f" (表: {sm['table_name']}, 字段: {sm['column_name']})"
        records.append({
            "text": text,
            "source_type": "semantic_model",
            "source_id": sm["id"],
            "metadata": {"table_name": sm["table_name"], "column_name": sm["column_name"], "business_name": sm["business_name"]},
        })

    # 业务知识
    bk_rows = await db.execute_query(
        "SELECT * FROM business_knowledge WHERE agent_id = :aid", {"aid": agent_id}
    )
    for bk in bk_rows:
        text = f"{bk['title']}: {bk['content']}"
        if bk.get("synonyms"):
            text += f" 同义词: {bk['synonyms']}"
        records.append({
            "text": text,
            "source_type": "business_knowledge",
            "source_id": bk["id"],
            "metadata": {"title": bk["title"], "knowledge_type": bk["knowledge_type"]},
        })

    if not records:
        return {"synced": 0, "message": "无知识需要同步"}

    # 批量向量化
    texts = [r["text"] for r in records]
    vectors = await emb_svc.embed_texts(texts)

    # 构建 VectorRecord
    vec_records = []
    for i, r in enumerate(records):
        vec_records.append(VectorRecord(
            content=r["text"],
            vector=vectors[i],
            source_type=r["source_type"],
            source_id=r["source_id"],
            agent_id=agent_id,
            metadata=r["metadata"],
        ))

    vec_store.insert(agent_id, vec_records)
    return {"synced": len(vec_records), "message": f"同步完成，共 {len(vec_records)} 条知识"}


@router.get("/stats/{agent_id}")
async def knowledge_stats(agent_id: int):
    """查询向量库中的知识数量."""
    vec_store = get_vector_store()
    count = vec_store.count(agent_id)
    return {"agent_id": agent_id, "vector_count": count}


async def _index_semantic_model(sm: SemanticModel, record_id: int):
    """将单条语义模型同步到 Milvus."""
    emb_svc = get_embedding_service()
    vec_store = get_vector_store()

    text = f"{sm.business_name}"
    if sm.synonyms:
        text += f" 同义词: {sm.synonyms}"
    if sm.description:
        text += f" {sm.description}"
    text += f" (表: {sm.table_name}, 字段: {sm.column_name})"

    vector = await emb_svc.embed_query(text)
    vec_store.insert(sm.agent_id, [VectorRecord(
        content=text,
        vector=vector,
        source_type="semantic_model",
        source_id=record_id,
        agent_id=sm.agent_id,
        metadata={"table_name": sm.table_name, "column_name": sm.column_name, "business_name": sm.business_name},
    )])


async def _index_business_knowledge(bk: BusinessKnowledge, record_id: int):
    """将单条业务知识同步到 Milvus."""
    emb_svc = get_embedding_service()
    vec_store = get_vector_store()

    text = f"{bk.title}: {bk.content}"
    if bk.synonyms:
        text += f" 同义词: {bk.synonyms}"

    vector = await emb_svc.embed_query(text)
    vec_store.insert(bk.agent_id, [VectorRecord(
        content=text,
        vector=vector,
        source_type="business_knowledge",
        source_id=record_id,
        agent_id=bk.agent_id,
        metadata={"title": bk.title, "knowledge_type": bk.knowledge_type},
    )])
