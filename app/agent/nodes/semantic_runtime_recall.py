from app.services.embedding_service import get_embedding_service
from app.services.semantic_runtime import get_semantic_runtime_service
from app.services.vector_store import get_vector_store


async def semantic_runtime_recall_node(state: dict) -> dict:
    """召回当前问数需要的语义运行时上下文。"""
    agent_id = state.get("agent_id", 0)
    datasource_id = state.get("datasource_id")
    question = state.get("enhanced_question") or state.get("question", "")
    svc = get_semantic_runtime_service()
    domain_id = await resolve_runtime_domain_id(agent_id, datasource_id)

    try:
        runtime = await svc.build_runtime(
            agent_id=agent_id,
            datasource_id=datasource_id,
            domain_key="loan_risk",
            domain_id=domain_id,
        )
    except Exception as exc:
        return {
            "semantic_runtime": None,
            "runtime_evidence": [],
            "semantic_error": str(exc),
            "final_answer": f"知识召回不可用: {exc}",
        }

    evidence: list[dict] = []
    try:
        query_vector = await get_embedding_service().embed_query(question, agent_id=agent_id)
        evidence = [
            {
                "content": item.content,
                "score": round(item.score, 4),
                "source_type": item.source_type,
                "source_id": item.source_id,
                "metadata": item.metadata,
            }
            for item in get_vector_store().search(agent_id, query_vector)
        ]
    except Exception:
        evidence = keyword_runtime_evidence(question, runtime.model_dump())

    if not evidence:
        evidence = keyword_runtime_evidence(question, runtime.model_dump())

    return {
        "semantic_runtime": runtime.model_dump(),
        "runtime_evidence": evidence[:8],
        "semantic_error": None,
    }


async def resolve_runtime_domain_id(agent_id: int, datasource_id: int | None) -> int | None:
    """Prefer the semantic layer explicitly selected on the agent."""
    domain = await get_semantic_runtime_service().get_agent_bound_domain(agent_id)
    if domain is None:
        return None
    if datasource_id and domain.datasource_id and domain.datasource_id != datasource_id:
        return None
    return domain.id


def keyword_runtime_evidence(question: str, runtime: dict, limit: int = 8) -> list[dict]:
    normalized = question.lower().replace(" ", "")
    candidates: list[dict] = []
    for asset_type, collection, key_field in (
        ("semantic_metric", runtime.get("metrics", []), "metric_key"),
        ("semantic_concept", runtime.get("concepts", []), "concept_key"),
        ("semantic_rule", runtime.get("rules", []), "rule_key"),
        ("logic_form_template", runtime.get("templates", []), "template_key"),
    ):
        for item in collection:
            tokens = [item.get("name", ""), item.get("description", ""), *item.get("synonyms", [])]
            score = sum(len(token) for token in tokens if token and token.lower() in normalized)
            if score:
                candidates.append(
                    {
                        "content": f"{item.get('name')}: {item.get('description', '')}",
                        "score": float(score),
                        "source_type": asset_type,
                        "source_id": item.get("id") or 0,
                        "metadata": {
                            "asset_key": item.get(key_field, ""),
                            "asset_type": asset_type,
                        },
                    }
                )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:limit]
