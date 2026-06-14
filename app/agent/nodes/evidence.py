from app.services.embedding_service import get_embedding_service
from app.services.vector_store import get_vector_store


async def evidence_recall_node(state: dict) -> dict:
    """知识召回节点：从 Milvus 向量库检索相关业务知识."""
    question = state.get("question", "")
    agent_id = state.get("agent_id", 0)

    if not agent_id or not question:
        return {"evidence": []}

    emb_svc = get_embedding_service()
    vec_store = get_vector_store()

    # 1. 向量化问题
    query_vector = await emb_svc.embed_query(question)

    # 2. 从 Milvus 搜索
    results = vec_store.search(agent_id, query_vector)

    # 3. 组装 evidence
    evidence = [
        {
            "content": r.content,
            "score": round(r.score, 4),
            "source_type": r.source_type,
            "source_id": r.source_id,
            "metadata": r.metadata,
        }
        for r in results
    ]

    return {"evidence": evidence}
