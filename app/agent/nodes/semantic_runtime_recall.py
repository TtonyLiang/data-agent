"""语义运行时召回节点 —— 加载语义层资产并构建 SemanticRuntime。

SemanticRuntimeRecallNode 负责:
1. 按 agent_id / domain_key / domain_id 从管理库加载语义层资产。
2. 组装 SemanticRuntime 对象(metrics/mappings/rules/concepts/relations/templates)。
3. 向量召回(可选):从 Milvus 检索语义资产向量,作为额外证据。
4. 向量召回失败时安全降级到关键词证据(keyword_runtime_evidence)。

SemanticRuntime 贯穿后续所有语义节点(校验、编译、修复、NL2LF 后处理)。
"""

import logging

from app.agent.ontology_evidence import build_ontology_evidence
from app.services.embedding_service import get_embedding_service
from app.services.ontology_service import get_ontology_service
from app.services.query_context import build_query_context
from app.services.semantic_runtime import get_semantic_runtime_service
from app.services.vector_store import get_vector_store
from app.utils.logging_helpers import (
    json_for_log,
    log_node_end,
    log_node_error,
    log_node_start,
    truncate_text,
)

logger = logging.getLogger(__name__)


async def semantic_runtime_recall_node(state: dict) -> dict:
    """召回当前问数需要的语义运行时上下文。"""
    log_node_start(
        logger,
        "semantic_runtime_recall",
        state,
        keys=("trace_id", "agent_id", "datasource_id", "enhanced_question", "question"),
    )
    agent_id = state.get("agent_id", 0)
    datasource_id = state.get("datasource_id")
    question = state.get("enhanced_question") or state.get("question", "")
    svc = get_semantic_runtime_service()
    domain_id = await resolve_runtime_domain_id(agent_id, datasource_id)
    logger.info(
        "semantic runtime resolved domain agent_id=%s datasource_id=%s domain_id=%s question=%s",
        agent_id,
        datasource_id,
        domain_id,
        truncate_text(question, 600),
    )

    try:
        runtime = await svc.build_runtime(
            agent_id=agent_id,
            datasource_id=datasource_id,
            domain_id=domain_id,
        )
    except Exception as exc:
        log_node_error(logger, "semantic_runtime_recall", exc, state)
        result = {
            "semantic_runtime": None,
            "runtime_evidence": [],
            "ontology_context": None,
            "ontology_evidence": {},
            "query_context": {
                "question": question,
                "domain": {},
                "ontology": {},
                "ontology_context": {},
                "bridge": {},
                "query_capabilities": [],
                "release": None,
                "evidence": {},
                "warnings": [
                    {
                        "code": "semantic_runtime_unavailable",
                        "message": "语义运行时不可用，未构建统一 query_context",
                        "details": {"error": str(exc)},
                    }
                ],
            },
            "semantic_error": str(exc),
            "final_answer": f"知识召回不可用: {exc}",
        }
        log_node_end(logger, "semantic_runtime_recall", result)
        return result

    evidence: list[dict] = []
    try:
        query_vector = await get_embedding_service().embed_query(question, agent_id=agent_id)
        logger.info("semantic runtime embedding generated dims=%s", len(query_vector or []))
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
        logger.info("semantic runtime vector evidence count=%s", len(evidence))
    except Exception as exc:
        logger.exception(
            "semantic runtime vector recall failed, fallback to keyword evidence: %s", exc
        )
        evidence = keyword_runtime_evidence(question, runtime.model_dump())

    if not evidence:
        logger.info("semantic runtime vector evidence empty, fallback to keyword evidence")
        evidence = keyword_runtime_evidence(question, runtime.model_dump())

    result = {
        "semantic_runtime": runtime.model_dump(),
        "runtime_evidence": evidence[:8],
        "semantic_error": None,
    }
    # Ontology is a sibling of the semantic runtime: it gives the Agent
    # business objects and governed actions while the semantic runtime keeps
    # metric-to-SQL mappings.  Loading it here makes both available in one
    # deterministic graph observation.
    try:
        ontology_context = await get_ontology_service().build_agent_context(
            domain_id,
            role=str(state.get("user_role") or "user"),
        )
    except Exception as exc:
        logger.warning(
            "ontology context unavailable agent_id=%s domain_id=%s error=%s",
            agent_id,
            domain_id,
            exc,
        )
        ontology_context = None
    result["ontology_context"] = ontology_context
    result["ontology_evidence"] = build_ontology_evidence(question, ontology_context)
    runtime_payload = runtime.model_dump()
    try:
        result["query_context"] = build_query_context(
            question,
            runtime_payload,
            ontology_context,
            result["ontology_evidence"],
        )
    except Exception as exc:
        logger.warning(
            "query context unavailable agent_id=%s domain_id=%s error=%s",
            agent_id,
            domain_id,
            exc,
        )
        result["query_context"] = {
            "question": question,
            "domain": runtime_payload.get("domain") or {},
            "ontology": ontology_context or {},
            "ontology_context": ontology_context or {},
            "bridge": {},
            "query_capabilities": [],
            "release": (ontology_context or {}).get("release")
            if isinstance(ontology_context, dict)
            else None,
            "evidence": result["ontology_evidence"],
            "warnings": [
                {
                    "code": "query_context_build_failed",
                    "message": "统一 query_context 构建失败，已保留旧语义召回结果",
                    "details": {"error": str(exc)},
                }
            ],
        }
    logger.info(
        "semantic runtime recalled counts=%s evidence=%s",
        json_for_log(
            {
                "concepts": len(runtime_payload.get("concepts", [])),
                "relations": len(runtime_payload.get("relations", [])),
                "metrics": len(runtime_payload.get("metrics", [])),
                "rules": len(runtime_payload.get("rules", [])),
                "mappings": len(runtime_payload.get("mappings", [])),
                "templates": len(runtime_payload.get("templates", [])),
            }
        ),
        json_for_log(evidence[:8]),
    )
    log_node_end(
        logger,
        "semantic_runtime_recall",
        {
            "semantic_error": None,
            "runtime_evidence_count": len(evidence[:8]),
            "runtime_counts": {
                "metrics": len(runtime_payload.get("metrics", [])),
                "mappings": len(runtime_payload.get("mappings", [])),
            },
            "ontology_match_count": result["ontology_evidence"].get("count", 0),
        },
    )
    return result


async def resolve_runtime_domain_id(agent_id: int, datasource_id: int | None) -> int | None:
    """Prefer the semantic layer explicitly selected on the agent."""
    domain = await get_semantic_runtime_service().get_agent_bound_domain(agent_id)
    if domain is None:
        logger.info("semantic runtime no agent-bound domain agent_id=%s", agent_id)
        return None
    if datasource_id and domain.datasource_id and domain.datasource_id != datasource_id:
        logger.info(
            "semantic runtime agent-bound domain skipped by datasource mismatch "
            "agent_id=%s domain_id=%s domain_datasource_id=%s request_datasource_id=%s",
            agent_id,
            domain.id,
            domain.datasource_id,
            datasource_id,
        )
        return None
    logger.info(
        "semantic runtime using agent-bound domain agent_id=%s domain_id=%s", agent_id, domain.id
    )
    return domain.id


def keyword_runtime_evidence(question: str, runtime: dict, limit: int = 8) -> list[dict]:
    """Build keyword-based semantic evidence when embedding or vector recall is unavailable."""
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
