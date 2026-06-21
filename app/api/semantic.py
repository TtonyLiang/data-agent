"""语义层管理 API —— 语义领域、资产、快照与向量同步的 REST 接口。

本模块是语义层配置的对外入口,所有操作都委托给 SemanticRuntimeService。

核心端点:
- /domains:语义领域的 CRUD、复制、导入导出。
- /domains/{id}/snapshots:版本快照的创建、查看、差异对比、回滚。
- /assets/{domain_id}:语义资产的 CRUD(概念/指标/映射/规则/关系/模板)。
- /sync-vector/{domain_id}:把语义资产向量化并同步到 Milvus。
- /logic-form/validate:调试用,校验 LogicForm 并尝试编译。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query

from app.models.knowledge import LogicForm, SemanticAssetPayload, SemanticDomain
from app.services.embedding_service import get_embedding_service
from app.services.semantic_runtime import get_semantic_runtime_service
from app.services.vector_store import VectorRecord, get_vector_store

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# 语义领域管理
# ============================================================


@router.get("/domains")
async def list_domains(agent_id: int):
    """列出指定智能体的语义领域列表。"""
    svc = get_semantic_runtime_service()
    domains = await svc.list_domains(agent_id)
    return {"domains": [domain.model_dump() for domain in domains]}


@router.get("/domains/all")
async def list_all_domains():
    """列出所有语义领域(管理页面用)。"""
    svc = get_semantic_runtime_service()
    domains = await svc.list_all_domains()
    return {"domains": [domain.model_dump() for domain in domains]}


@router.post("/domains")
async def upsert_domain(payload: SemanticDomain):
    """创建或更新语义领域。相同 domain_key+agent_id 时更新。"""
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
    """删除语义领域及其全部子资产。"""
    svc = get_semantic_runtime_service()
    deleted = await svc.delete_domain(domain_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="语义领域不存在")
    return {"deleted": True, "id": domain_id, "message": "语义层已删除"}


@router.post("/domains/{domain_id}/copy")
async def copy_domain(domain_id: int, request: dict):
    """复制语义领域(含全部资产)到新领域。"""
    svc = get_semantic_runtime_service()
    try:
        new_id = await svc.copy_domain(domain_id, request or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    domain = await svc.get_domain(new_id)
    return {
        "id": new_id,
        "domain": domain.model_dump() if domain else None,
        "message": "语义层已复制",
    }


@router.get("/domains/{domain_id}/export")
async def export_domain(domain_id: int):
    """导出语义领域为 JSON bundle。"""
    svc = get_semantic_runtime_service()
    try:
        return await svc.export_domain_bundle(domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/domains/import")
async def import_domain(request: dict):
    """导入语义领域 bundle。domain_key 重复时报错。"""
    svc = get_semantic_runtime_service()
    try:
        domain_id = await svc.import_domain_bundle(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    domain = await svc.get_domain(domain_id)
    return {
        "id": domain_id,
        "domain": domain.model_dump() if domain else None,
        "message": "语义层已导入",
    }


@router.post("/domains/{domain_id}/validate")
async def validate_domain(domain_id: int):
    """校验语义资产:物理表/字段是否已采集、引用是否完整。"""
    svc = get_semantic_runtime_service()
    try:
        return await svc.validate_domain_assets(domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ============================================================
# 版本快照
# ============================================================


@router.post("/domains/{domain_id}/snapshot")
async def create_domain_snapshot(domain_id: int, request: dict | None = None):
    """创建语义层版本快照。"""
    svc = get_semantic_runtime_service()
    payload = request or {}
    try:
        snapshot_id = await svc.create_snapshot(
            domain_id,
            name=payload.get("name"),
            description=payload.get("description"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": snapshot_id, "message": "语义层快照已创建"}


@router.get("/domains/{domain_id}/snapshots")
async def list_domain_snapshots(domain_id: int):
    """列出语义层的版本快照。"""
    svc = get_semantic_runtime_service()
    if await svc.get_domain(domain_id) is None:
        raise HTTPException(status_code=404, detail="语义领域不存在")
    return {"snapshots": await svc.list_snapshots(domain_id)}


@router.get("/domains/{domain_id}/snapshots/{snapshot_id}")
async def get_domain_snapshot(domain_id: int, snapshot_id: int):
    """获取单个快照详情。"""
    svc = get_semantic_runtime_service()
    try:
        return {"snapshot": await svc.get_snapshot(domain_id, snapshot_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/domains/{domain_id}/snapshots/{snapshot_id}/diff")
async def diff_domain_snapshot(domain_id: int, snapshot_id: int):
    """对比当前语义层与快照的差异。"""
    svc = get_semantic_runtime_service()
    try:
        return await svc.diff_snapshot(domain_id, snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/domains/{domain_id}/snapshots/{snapshot_id}/rollback")
async def rollback_domain_snapshot(domain_id: int, snapshot_id: int):
    """回滚语义层到快照版本(替换全部资产)。"""
    svc = get_semantic_runtime_service()
    try:
        return await svc.rollback_snapshot(domain_id, snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ============================================================
# 语义资产管理
# ============================================================


@router.get("/assets/{domain_id}")
async def list_assets(domain_id: int, asset_type: str | None = Query(default=None, alias="type")):
    """列出语义资产,可按 asset_type 过滤。"""
    svc = get_semantic_runtime_service()
    domain = await svc.get_domain(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="语义领域不存在")
    try:
        return {
            "domain": domain.model_dump(),
            "assets": await svc.list_assets(domain_id, asset_type),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/assets/{domain_id}")
async def upsert_asset(domain_id: int, payload: SemanticAssetPayload):
    """创建或更新语义资产。"""
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
    """删除单个语义资产。"""
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


# ============================================================
# 运行时与调试
# ============================================================


@router.post("/runtime/build")
async def build_runtime(request: dict):
    """手动构建语义运行时(调试用)。"""
    svc = get_semantic_runtime_service()
    try:
        runtime = await svc.build_runtime(
            agent_id=int(request.get("agent_id", 1)),
            datasource_id=request.get("datasource_id"),
            domain_key=request.get("domain_key"),
            domain_id=request.get("domain_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"runtime": runtime.model_dump()}


@router.post("/logic-form/validate")
async def validate_logic_form(request: dict):
    """调试用:校验 LogicForm 并尝试编译 SQL。"""
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


# ============================================================
# 向量同步
# ============================================================


@router.post("/sync-vector/{domain_id}")
async def sync_domain_to_vector(domain_id: int):
    """把语义资产向量化并同步到 Milvus,供知识召回使用。

    流程:
    1. 构建语义运行时。
    2. 遍历概念/指标/规则/模板,拼接可向量化的文本。
    3. 调用 embedding 服务批量向量化。
    4. 清空旧向量后插入新向量。
    """
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

    # 第2步:遍历各类资产,拼接可向量化的文本
    records = []
    # 概念:名称 + 类型 + 描述 + 同义词
    for item in runtime.concepts:
        synonyms = " ".join(item.synonyms)
        records.append(
            {
                "text": f"{item.name} {item.concept_type} {item.description or ''} {synonyms}",
                "source_type": "semantic_concept",
                "source_id": item.id or 0,
                "metadata": {"asset_key": item.concept_key, "asset_type": "concept"},
            }
        )
    # 指标:名称 + 类型 + 描述 + 同义词
    for item in runtime.metrics:
        records.append(
            {
                "text": f"{item.name} 指标 {item.description or ''} {' '.join(item.synonyms)}",
                "source_type": "semantic_metric",
                "source_id": item.id or 0,
                "metadata": {"asset_key": item.metric_key, "asset_type": "metric"},
            }
        )
    # 规则:名称 + 类型 + 描述
    for item in runtime.rules:
        records.append(
            {
                "text": f"{item.name} 规则 {item.description or ''}",
                "source_type": "semantic_rule",
                "source_id": item.id or 0,
                "metadata": {"asset_key": item.rule_key, "asset_type": "rule"},
            }
        )
    # 模板:名称 + 类型 + 描述 + 样例
    for item in runtime.templates:
        examples_text = json.dumps(item.examples, ensure_ascii=False)
        records.append(
            {
                "text": f"{item.name} LogicForm {item.description or ''} {examples_text}",
                "source_type": "logic_form_template",
                "source_id": item.id or 0,
                "metadata": {"asset_key": item.template_key, "asset_type": "template"},
            }
        )

    # 第3步:清空旧向量,无资产时直接返回
    vec_store = get_vector_store()
    vec_store.delete_collection(domain.agent_id)
    if not records:
        return {"synced": 0, "message": "无语义资产需要同步"}

    # 第4步:批量向量化并插入
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
    logger.info("sync_vector domain_id=%s agent_id=%s synced=%s", domain_id, domain.agent_id, len(records))
    return {"synced": len(records), "message": f"同步完成，共 {len(records)} 条语义资产"}
