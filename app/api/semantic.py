from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from app.models.knowledge import LogicForm, SemanticAssetPayload, SemanticDomain
from app.services.embedding_service import get_embedding_service
from app.services.semantic_runtime import get_semantic_runtime_service
from app.services.vector_store import VectorRecord, get_vector_store

router = APIRouter()


@router.get("/domains")
async def list_domains(agent_id: int):
    svc = get_semantic_runtime_service()
    domains = await svc.list_domains(agent_id)
    return {"domains": [domain.model_dump() for domain in domains]}


@router.get("/domains/all")
async def list_all_domains():
    svc = get_semantic_runtime_service()
    domains = await svc.list_all_domains()
    return {"domains": [domain.model_dump() for domain in domains]}


@router.post("/domains")
async def upsert_domain(payload: SemanticDomain):
    svc = get_semantic_runtime_service()
    try:
        domain_id = await svc.upsert_domain(
            payload.model_dump(exclude={"created_at", "updated_at"})
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    domain = await svc.get_domain(domain_id)
    return {
        "id": domain_id,
        "domain": domain.model_dump() if domain else None,
        "message": "语义层已保存",
    }


@router.delete("/domains/{domain_id}")
async def delete_domain(domain_id: int):
    svc = get_semantic_runtime_service()
    deleted = await svc.delete_domain(domain_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="语义领域不存在")
    return {"deleted": True, "id": domain_id, "message": "语义层已删除"}


@router.get("/assets/{domain_id}")
async def list_assets(domain_id: int, asset_type: str | None = Query(default=None, alias="type")):
    svc = get_semantic_runtime_service()
    domain = await svc.get_domain(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="语义领域不存在")
    try:
        return {"domain": domain.model_dump(), "assets": await svc.list_assets(domain_id, asset_type)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/assets/{domain_id}")
async def upsert_asset(domain_id: int, payload: SemanticAssetPayload):
    svc = get_semantic_runtime_service()
    if await svc.get_domain(domain_id) is None:
        raise HTTPException(status_code=404, detail="语义领域不存在")
    try:
        asset_id = await svc.upsert_asset(domain_id, payload.asset_type, payload.data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": asset_id, "asset_type": payload.asset_type, "message": "语义资产已保存"}


@router.delete("/assets/{domain_id}/{asset_type}/{asset_id}")
async def delete_asset(domain_id: int, asset_type: str, asset_id: int):
    svc = get_semantic_runtime_service()
    if await svc.get_domain(domain_id) is None:
        raise HTTPException(status_code=404, detail="语义领域不存在")
    try:
        deleted = await svc.delete_asset(domain_id, asset_type, asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="语义资产不存在")
    return {"deleted": True, "asset_type": asset_type, "id": asset_id, "message": "语义资产已删除"}


@router.post("/runtime/build")
async def build_runtime(request: dict):
    svc = get_semantic_runtime_service()
    try:
        runtime = await svc.build_runtime(
            agent_id=int(request.get("agent_id", 1)),
            datasource_id=request.get("datasource_id"),
            domain_key=request.get("domain_key", "loan_risk"),
            domain_id=request.get("domain_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"runtime": runtime.model_dump()}


@router.post("/logic-form/validate")
async def validate_logic_form(request: dict):
    svc = get_semantic_runtime_service()
    logic_form = LogicForm(**request.get("logic_form", request))
    try:
        runtime = await svc.build_runtime(
            agent_id=int(request.get("agent_id", 1)),
            datasource_id=request.get("datasource_id"),
            domain_key=logic_form.domain_key,
            domain_id=request.get("domain_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    validation = svc.validate_logic_form(logic_form, runtime)
    compiled = None
    if validation.valid:
        compiled = svc.compile_logic_form(logic_form, runtime).model_dump()
    return {
        "logic_form": logic_form.model_dump(),
        "validation": validation.model_dump(),
        "compiled_query": compiled,
    }


@router.post("/sync-vector/{domain_id}")
async def sync_domain_to_vector(domain_id: int):
    svc = get_semantic_runtime_service()
    domain = await svc.get_domain(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="语义领域不存在")

    runtime = await svc.build_runtime(
        agent_id=domain.agent_id,
        datasource_id=domain.datasource_id,
        domain_key=domain.domain_key,
        domain_id=domain.id,
    )
    records = []
    for item in runtime.concepts:
        records.append(
            {
                "text": f"{item.name} {item.concept_type} {item.description or ''} {' '.join(item.synonyms)}",
                "source_type": "semantic_concept",
                "source_id": item.id or 0,
                "metadata": {"asset_key": item.concept_key, "asset_type": "concept"},
            }
        )
    for item in runtime.metrics:
        records.append(
            {
                "text": f"{item.name} 指标 {item.description or ''} {' '.join(item.synonyms)}",
                "source_type": "semantic_metric",
                "source_id": item.id or 0,
                "metadata": {"asset_key": item.metric_key, "asset_type": "metric"},
            }
        )
    for item in runtime.rules:
        records.append(
            {
                "text": f"{item.name} 规则 {item.description or ''}",
                "source_type": "semantic_rule",
                "source_id": item.id or 0,
                "metadata": {"asset_key": item.rule_key, "asset_type": "rule"},
            }
        )
    for item in runtime.templates:
        records.append(
            {
                "text": f"{item.name} LogicForm {item.description or ''} {json.dumps(item.examples, ensure_ascii=False)}",
                "source_type": "logic_form_template",
                "source_id": item.id or 0,
                "metadata": {"asset_key": item.template_key, "asset_type": "template"},
            }
        )

    vec_store = get_vector_store()
    vec_store.delete_collection(domain.agent_id)
    if not records:
        return {"synced": 0, "message": "无语义资产需要同步"}

    vectors = await get_embedding_service().embed_texts(
        [item["text"] for item in records],
        agent_id=domain.agent_id,
    )
    vec_store.insert(
        domain.agent_id,
        [
            VectorRecord(
                content=item["text"],
                vector=vectors[index],
                source_type=item["source_type"],
                source_id=item["source_id"],
                agent_id=domain.agent_id,
                metadata=item["metadata"],
            )
            for index, item in enumerate(records)
        ],
    )
    return {"synced": len(records), "message": f"同步完成，共 {len(records)} 条语义资产"}
