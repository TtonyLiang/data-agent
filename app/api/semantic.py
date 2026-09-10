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
from copy import deepcopy
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import (
    get_current_user,
    require_agent_access,
    require_data_engineer,
    require_domain_access,
    require_model_editor,
    require_model_publisher,
)
from app.models.knowledge import LogicForm, SemanticAssetPayload, SemanticDomain
from app.models.user import PublicUser, is_technical_role
from app.services.decision_audit_service import canonical_sha256
from app.services.embedding_service import get_embedding_service
from app.services.model_release_service import get_model_release_service
from app.services.ontology_semantic_bridge import validate_semantic_relation_bindings
from app.services.ontology_service import get_ontology_service
from app.services.semantic_runtime import get_semantic_runtime_service
from app.services.vector_store import VectorRecord, get_vector_store

logger = logging.getLogger(__name__)
router = APIRouter()

SEMANTIC_ASSET_KEY_FIELDS = {
    "concept": "concept_key",
    "relation": "relation_key",
    "metric": "metric_key",
    "rule": "rule_key",
    "mapping": "asset_key",
    "template": "template_key",
}
SEMANTIC_TECH_FIELD_DEFAULTS: dict[str, dict[str, Any]] = {
    "metric": {"formula_sql": "", "base_table": "", "time_field": None},
    "relation": {"join_path": [], "conditions": []},
    "template": {
        "intent_type": "metric_query",
        "required_slots": [],
        "optional_slots": [],
        "compile_strategy": {},
    },
}
SEMANTIC_TECH_ONLY_ASSET_TYPES = {"mapping"}
SEMANTIC_TECH_ONLY_DELETE_ASSET_TYPES = {"mapping", "relation", "metric", "template"}
SEMANTIC_TECH_FIELD_DETAIL = "SQL、物理字段、JOIN 路径和 LogicForm 编译配置由技术人员维护"


def _validate_vector_release_lineage(model_release: dict[str, Any]) -> dict[str, str]:
    """Validate the immutable hashes before creating a release-scoped index."""
    semantic_hash = str(model_release.get("semantic_snapshot_hash") or "").strip()
    ontology_hash = str(model_release.get("ontology_definition_hash") or "").strip()
    model_hash = str(model_release.get("model_hash") or "").strip()
    if not semantic_hash or not ontology_hash or not model_hash:
        raise HTTPException(
            status_code=409,
            detail="激活企业模型版本缺少完整内容哈希，不能生成正式语义检索索引",
        )
    expected_model_hash = canonical_sha256(
        {
            "format": "wenqu-enterprise-model-release/v1",
            "semantic_snapshot_hash": semantic_hash,
            "ontology_definition_hash": ontology_hash,
        }
    )
    if model_hash != expected_model_hash:
        raise HTTPException(
            status_code=409,
            detail="激活企业模型版本哈希校验失败，不能生成正式语义检索索引",
        )
    return {
        "semantic_snapshot_hash": semantic_hash,
        "ontology_definition_hash": ontology_hash,
        "model_hash": model_hash,
    }


def _canonical_permission_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return None if stripped == "" else stripped
    if isinstance(value, (list, tuple)):
        normalized = [_canonical_permission_value(item) for item in value]
        return [item for item in normalized if item is not None]
    if isinstance(value, dict):
        return {
            str(key): _canonical_permission_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if _canonical_permission_value(item) is not None
        }
    return value


def _permission_values_equal(left: Any, right: Any) -> bool:
    return _canonical_permission_value(left) == _canonical_permission_value(right)


def _is_default_or_empty(value: Any, default: Any) -> bool:
    return _permission_values_equal(value, default) or _permission_values_equal(value, None)


async def _get_existing_semantic_asset(
    svc,
    domain_id: int,
    asset_type: str,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    key_field = SEMANTIC_ASSET_KEY_FIELDS.get(asset_type)
    if not key_field:
        return None
    assets = await svc.list_assets(domain_id, asset_type)
    items = (assets or {}).get(asset_type) or []
    raw_id = data.get("id")
    if raw_id is not None:
        try:
            target_id = int(raw_id)
        except (TypeError, ValueError):
            target_id = None
        if target_id is not None:
            for item in items:
                if int(item.get("id") or 0) == target_id:
                    return dict(item)
    key_value = str(data.get(key_field) or "").strip()
    if key_value:
        for item in items:
            if str(item.get(key_field) or "").strip() == key_value:
                return dict(item)
    return None


async def _prepare_semantic_asset_for_role(
    svc,
    domain_id: int,
    asset_type: str,
    data: dict[str, Any],
    current_user: PublicUser,
) -> dict[str, Any]:
    """Preserve technical fields for business edits and reject attempted changes."""
    prepared = dict(data)
    if is_technical_role(current_user.role):
        return prepared
    if asset_type in SEMANTIC_TECH_ONLY_ASSET_TYPES:
        raise HTTPException(status_code=403, detail=SEMANTIC_TECH_FIELD_DETAIL)
    tech_defaults = SEMANTIC_TECH_FIELD_DEFAULTS.get(asset_type)
    if not tech_defaults:
        return prepared
    existing = await _get_existing_semantic_asset(svc, domain_id, asset_type, prepared)
    changed_fields: list[str] = []
    key_field = SEMANTIC_ASSET_KEY_FIELDS.get(asset_type)
    if (
        existing
        and key_field
        and key_field in prepared
        and str(prepared.get(key_field) or "") != str(existing.get(key_field) or "")
    ):
        changed_fields.append(key_field)
    for field, default in tech_defaults.items():
        if field not in prepared:
            prepared[field] = existing.get(field) if existing else deepcopy(default)
            continue
        requested = prepared.get(field)
        if existing:
            if not _permission_values_equal(requested, existing.get(field)):
                changed_fields.append(field)
        elif not _is_default_or_empty(requested, default):
            changed_fields.append(field)
    if asset_type == "relation":
        existing_metadata = (
            dict(existing.get("metadata") or {}) if existing else {}
        )
        requested_metadata = prepared.get("metadata")
        if requested_metadata is None:
            prepared["metadata"] = deepcopy(existing_metadata)
        else:
            requested_metadata = dict(requested_metadata)
            existing_link_key = existing_metadata.get("link_key")
            if "link_key" in requested_metadata:
                requested_link_key = requested_metadata.get("link_key")
                if existing and not _permission_values_equal(
                    requested_link_key, existing_link_key
                ):
                    changed_fields.append("metadata.link_key")
                elif not existing and _canonical_permission_value(requested_link_key) is not None:
                    changed_fields.append("metadata.link_key")
            elif existing and existing_link_key is not None:
                requested_metadata["link_key"] = existing_link_key
            prepared["metadata"] = requested_metadata
    if changed_fields:
        raise HTTPException(
            status_code=403,
            detail=f"{SEMANTIC_TECH_FIELD_DETAIL}: {', '.join(changed_fields)}",
        )
    return prepared


def _prepare_semantic_bundle_for_role(
    bundle: dict[str, Any], current_user: PublicUser
) -> dict[str, Any]:
    prepared = deepcopy(bundle)
    if is_technical_role(current_user.role):
        return prepared
    domain = prepared.get("domain") or {}
    if domain.get("datasource_id") is not None or domain.get("agent_id") is not None:
        raise HTTPException(
            status_code=403,
            detail="业务人员可以导入业务定义，但不能导入默认数据源或验证客户端绑定",
        )
    assets = prepared.get("assets") or {}
    if not isinstance(assets, dict):
        return prepared
    for asset_type, tech_defaults in SEMANTIC_TECH_FIELD_DEFAULTS.items():
        for item in assets.get(asset_type, []) or []:
            if not isinstance(item, dict):
                continue
            for field, default in tech_defaults.items():
                if field not in item:
                    item[field] = deepcopy(default)
                    continue
                if not _is_default_or_empty(item.get(field), default):
                    raise HTTPException(
                        status_code=403,
                        detail=f"{SEMANTIC_TECH_FIELD_DETAIL}: {asset_type}.{field}",
                    )
    for item in assets.get("relation", []) or []:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if _canonical_permission_value(metadata.get("link_key")) is not None:
            raise HTTPException(
                status_code=403,
                detail=f"{SEMANTIC_TECH_FIELD_DETAIL}: relation.metadata.link_key",
            )
    if assets.get("mapping"):
        raise HTTPException(status_code=403, detail=SEMANTIC_TECH_FIELD_DETAIL)
    return prepared


async def _relation_binding_errors(
    domain_id: int,
    relations: list[dict],
    *,
    require_active: bool = True,
) -> list[dict]:
    link_types = await get_ontology_service().list_link_types(domain_id)
    return validate_semantic_relation_bindings(
        link_types,
        relations,
        require_active=require_active,
    )


# ============================================================
# 语义领域管理
# ============================================================


@router.get("/domains")
async def list_domains(agent_id: int, current_user: PublicUser = Depends(get_current_user)):
    """列出指定智能体的语义领域列表。"""
    await require_agent_access(agent_id, current_user)
    svc = get_semantic_runtime_service()
    domains = await svc.list_domains(agent_id)
    return {"domains": [domain.model_dump() for domain in domains]}


@router.get("/domains/all")
async def list_all_domains(_: PublicUser = Depends(require_data_engineer)):
    """列出所有语义领域(管理页面用)。"""
    svc = get_semantic_runtime_service()
    domains = await svc.list_all_domains()
    return {"domains": [domain.model_dump() for domain in domains]}


@router.post("/domains")
async def upsert_domain(
    payload: SemanticDomain,
    current_user: PublicUser = Depends(require_model_editor),
):
    """创建或更新公司内部业务领域；domain_key 在当前单公司模型库内唯一。"""
    svc = get_semantic_runtime_service()
    if not is_technical_role(current_user.role):
        existing = await svc.get_domain(payload.id) if payload.id else None
        existing_datasource_id = (
            int(existing.datasource_id) if existing and existing.datasource_id else None
        )
        existing_agent_id = int(existing.agent_id) if existing and existing.agent_id else None
        requested_datasource_id = (
            int(payload.datasource_id) if payload.datasource_id else None
        )
        requested_agent_id = int(payload.agent_id) if payload.agent_id else None
        if (
            requested_datasource_id != existing_datasource_id
            or requested_agent_id != existing_agent_id
        ):
            raise HTTPException(
                status_code=403,
                detail="业务人员可以维护业务定义，但不能修改默认数据源或验证客户端绑定",
            )
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
        "message": "业务领域已保存",
    }


@router.delete("/domains/{domain_id}")
async def delete_domain(domain_id: int, _: PublicUser = Depends(require_data_engineer)):
    """删除尚未产生版本或运行历史的空闲业务领域。"""
    svc = get_semantic_runtime_service()
    try:
        deleted = await svc.delete_domain(domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="语义领域不存在")
    return {"deleted": True, "id": domain_id, "message": "业务领域已删除"}


@router.post("/domains/{domain_id}/copy")
async def copy_domain(
    domain_id: int,
    request: dict,
    _: PublicUser = Depends(require_data_engineer),
):
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
        "message": "业务领域已复制",
    }


@router.get("/domains/{domain_id}/export")
async def export_domain(domain_id: int, _: PublicUser = Depends(require_model_editor)):
    """导出语义领域为 JSON bundle。"""
    svc = get_semantic_runtime_service()
    try:
        return await svc.export_domain_bundle(domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/domains/import")
async def import_domain(
    request: dict,
    current_user: PublicUser = Depends(require_model_editor),
):
    """导入语义领域 bundle。domain_key 重复时报错。"""
    svc = get_semantic_runtime_service()
    request = _prepare_semantic_bundle_for_role(request, current_user)
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
async def validate_domain(domain_id: int, _: PublicUser = Depends(require_model_editor)):
    """校验语义资产:物理表/字段是否已采集、引用是否完整。"""
    svc = get_semantic_runtime_service()
    try:
        result = await svc.validate_domain_assets(domain_id)
        assets = await svc.list_assets(domain_id, "relation")
        binding_errors = await _relation_binding_errors(
            domain_id, assets.get("relation") or []
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    errors = [
        *list(result.get("errors") or []),
        *[
            str(item.get("message") or "")
            for item in binding_errors
            if item.get("message")
        ],
    ]
    checks = dict(result.get("checks") or {})
    checks["ontology_relation_bindings"] = {
        "valid": not binding_errors,
        "errors": binding_errors,
    }
    return {**result, "valid": not errors, "errors": errors, "checks": checks}


# ============================================================
# 版本快照
# ============================================================


@router.post("/domains/{domain_id}/snapshot")
async def create_domain_snapshot(
    domain_id: int,
    request: dict | None = None,
    _: PublicUser = Depends(require_model_editor),
):
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
async def list_domain_snapshots(domain_id: int, _: PublicUser = Depends(require_model_editor)):
    """列出语义层的版本快照。"""
    svc = get_semantic_runtime_service()
    if await svc.get_domain(domain_id) is None:
        raise HTTPException(status_code=404, detail="语义领域不存在")
    return {"snapshots": await svc.list_snapshots(domain_id)}


@router.get("/domains/{domain_id}/snapshots/{snapshot_id}")
async def get_domain_snapshot(
    domain_id: int,
    snapshot_id: int,
    _: PublicUser = Depends(require_model_editor),
):
    """获取单个快照详情。"""
    svc = get_semantic_runtime_service()
    try:
        return {"snapshot": await svc.get_snapshot(domain_id, snapshot_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/domains/{domain_id}/snapshots/{snapshot_id}/diff")
async def diff_domain_snapshot(
    domain_id: int,
    snapshot_id: int,
    _: PublicUser = Depends(require_model_editor),
):
    """对比当前语义层与快照的差异。"""
    svc = get_semantic_runtime_service()
    try:
        return await svc.diff_snapshot(domain_id, snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/domains/{domain_id}/snapshots/{snapshot_id}/rollback")
async def rollback_domain_snapshot(
    domain_id: int,
    snapshot_id: int,
    _: PublicUser = Depends(require_model_publisher),
):
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
async def list_assets(
    domain_id: int,
    asset_type: str | None = Query(default=None, alias="type"),
    current_user: PublicUser = Depends(get_current_user),
):
    """列出语义资产,可按 asset_type 过滤。"""
    svc = get_semantic_runtime_service()
    domain = await svc.get_domain(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="语义领域不存在")
    await require_domain_access(domain_id, current_user)
    try:
        return {
            "domain": domain.model_dump(),
            "assets": await svc.list_assets(domain_id, asset_type),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/assets/{domain_id}")
async def upsert_asset(
    domain_id: int,
    payload: SemanticAssetPayload,
    current_user: PublicUser = Depends(require_model_editor),
):
    """创建或更新语义资产。"""
    svc = get_semantic_runtime_service()
    if await svc.get_domain(domain_id) is None:
        raise HTTPException(status_code=404, detail="语义领域不存在")
    asset_data = await _prepare_semantic_asset_for_role(
        svc,
        domain_id,
        payload.asset_type,
        payload.data,
        current_user,
    )
    try:
        if payload.asset_type == "relation":
            binding_errors = await _relation_binding_errors(
                domain_id,
                [asset_data],
                require_active=False,
            )
            if binding_errors:
                raise ValueError(str(binding_errors[0]["message"]))
        asset_id = await svc.upsert_asset(domain_id, payload.asset_type, asset_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": asset_id, "asset_type": payload.asset_type, "message": "语义资产已保存"}


@router.delete("/assets/{domain_id}/{asset_type}/{asset_id}")
async def delete_asset(
    domain_id: int,
    asset_type: str,
    asset_id: int,
    current_user: PublicUser = Depends(require_model_editor),
):
    """删除单个语义资产。"""
    svc = get_semantic_runtime_service()
    if await svc.get_domain(domain_id) is None:
        raise HTTPException(status_code=404, detail="语义领域不存在")
    if asset_type in SEMANTIC_TECH_ONLY_DELETE_ASSET_TYPES and not is_technical_role(
        current_user.role
    ):
        raise HTTPException(
            status_code=403,
            detail="带有物理绑定或运行编译配置的语义资产由技术人员删除",
        )
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


async def resolve_runtime_agent_id(svc, request: dict) -> int:
    """Resolve the consumer Agent server-side when a domain ID is supplied."""
    raw_agent_id = request.get("agent_id")
    preferred_agent_id = int(raw_agent_id) if raw_agent_id is not None else None
    raw_domain_id = request.get("domain_id")
    if raw_domain_id is None:
        return preferred_agent_id if preferred_agent_id is not None else 1
    agent_id = await svc.resolve_domain_agent(int(raw_domain_id), preferred_agent_id)
    if agent_id is None:
        raise ValueError("领域尚未绑定可执行的智能体")
    return agent_id


@router.post("/runtime/build")
async def build_runtime(request: dict, _: PublicUser = Depends(require_data_engineer)):
    """手动构建语义运行时(调试用)。"""
    svc = get_semantic_runtime_service()
    try:
        agent_id = (
            None
            if request.get("domain_id") is not None and request.get("agent_id") is None
            else await resolve_runtime_agent_id(svc, request)
        )
        runtime = await svc.build_runtime(
            agent_id=agent_id,
            datasource_id=request.get("datasource_id"),
            domain_key=request.get("domain_key"),
            domain_id=request.get("domain_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"runtime": runtime.model_dump()}


@router.post("/logic-form/validate")
async def validate_logic_form(request: dict, _: PublicUser = Depends(require_data_engineer)):
    """调试用:校验 LogicForm 并尝试编译 SQL。"""
    svc = get_semantic_runtime_service()
    logic_form = LogicForm(**request.get("logic_form", request))
    try:
        agent_id = (
            None
            if request.get("domain_id") is not None and request.get("agent_id") is None
            else await resolve_runtime_agent_id(svc, request)
        )
        runtime = await svc.build_runtime(
            agent_id=agent_id,
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
async def sync_domain_to_vector(domain_id: int, _: PublicUser = Depends(require_data_engineer)):
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
    execution_agent_ids = await svc.get_domain_agent_ids(domain_id)
    model_release = await get_model_release_service().get_active_release(domain_id)
    if model_release is None:
        raise HTTPException(
            status_code=409,
            detail="当前业务领域尚未激活统一企业模型版本，不能生成正式语义检索索引",
        )
    release_hashes = _validate_vector_release_lineage(model_release)
    model_release_id = int(model_release["id"])
    semantic_snapshot_id = int(model_release["semantic_snapshot_id"])
    runtime = await svc.build_runtime_from_snapshot(
        domain_id,
        semantic_snapshot_id,
        agent_id=None,
        expected_snapshot_hash=release_hashes["semantic_snapshot_hash"],
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

    # 第3步:Agent 只负责选择 embedding 配置；相同配置共享一个企业模型索引。
    embedding_service = get_embedding_service()
    embedding_profiles: dict[tuple[int | None, str], dict] = {}
    for agent_id in execution_agent_ids or [None]:
        identity = await embedding_service.get_index_identity(agent_id)
        profile_key = (
            int(identity["config_id"])
            if identity.get("config_id") is not None
            else None,
            str(identity["version"]),
        )
        embedding_profiles.setdefault(
            profile_key,
            {"agent_id": agent_id, "identity": identity},
        )

    vec_store = get_vector_store()
    if not records:
        for profile in embedding_profiles.values():
            identity = profile["identity"]
            vec_store.delete_collection(
                None,
                domain_id,
                model_release_id=model_release_id,
                semantic_snapshot_id=semantic_snapshot_id,
                embedding_model_config_id=identity.get("config_id"),
                embedding_model_version=str(identity["version"]),
            )
        return {
            "synced": 0,
            "agent_ids": execution_agent_ids,
            "message": "无语义资产需要同步",
        }

    # 第4步:按唯一 embedding 配置向量化并写入版本化企业集合。
    synced_indexes = []
    for profile in embedding_profiles.values():
        agent_id = profile["agent_id"]
        identity = profile["identity"]
        vectors = await embedding_service.embed_texts(
            [item["text"] for item in records],
            agent_id=agent_id,
        )
        vec_store.delete_collection(
            None,
            domain_id,
            model_release_id=model_release_id,
            semantic_snapshot_id=semantic_snapshot_id,
            embedding_model_config_id=identity.get("config_id"),
            embedding_model_version=str(identity["version"]),
        )
        vec_store.insert(
            None,
            [
                VectorRecord(
                    content=item["text"],
                    vector=vectors[index],
                    source_type=item["source_type"],
                    source_id=item["source_id"],
                    agent_id=0,
                    metadata={
                        **item["metadata"],
                        "domain_id": domain_id,
                        "model_release_id": model_release_id,
                        "semantic_snapshot_id": semantic_snapshot_id,
                        "semantic_snapshot_hash": release_hashes["semantic_snapshot_hash"],
                        "ontology_definition_hash": release_hashes[
                            "ontology_definition_hash"
                        ],
                        "model_hash": release_hashes["model_hash"],
                        "embedding_model_config_id": identity.get("config_id"),
                        "embedding_model_version": identity["version"],
                    },
                )
                for index, item in enumerate(records)
            ],
            domain_id=domain_id,
            model_release_id=model_release_id,
            semantic_snapshot_id=semantic_snapshot_id,
            embedding_model_config_id=identity.get("config_id"),
            embedding_model_version=str(identity["version"]),
            embedding_dimension=int(identity["dimension"]),
        )
        synced_indexes.append(
            {
                "embedding_model_config_id": identity.get("config_id"),
                "embedding_model_version": identity["version"],
                "dimension": identity["dimension"],
            }
        )
    logger.info(
        "sync_vector domain_id=%s model_release_id=%s semantic_snapshot_id=%s "
        "agent_ids=%s index_count=%s asset_count=%s",
        domain_id,
        model_release_id,
        semantic_snapshot_id,
        execution_agent_ids,
        len(synced_indexes),
        len(records),
    )
    return {
        "synced": len(records),
        "agent_ids": execution_agent_ids,
        "model_release_id": model_release_id,
        "semantic_snapshot_id": semantic_snapshot_id,
        **release_hashes,
        "embedding_indexes": synced_indexes,
        "message": (
            f"同步完成，共 {len(records)} 条语义资产，"
            f"已更新 {len(synced_indexes)} 个模型索引"
        ),
    }
