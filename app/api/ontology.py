"""REST API for business Ontology definition, publishing, runtime, and audit."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agent.ontology_tools import (
    ACTION_TOOL,
    QUERY_CAPABILITY_TOOL,
    QUERY_TOOL,
    _load_query_runtime_context,
    build_ontology_tool_definitions,
    build_query_capability_definitions,
    invoke_ontology_tool,
)
from app.api.deps import (
    get_current_user,
    require_data_engineer,
    require_domain_access,
    require_model_editor,
    require_model_publisher,
)
from app.models.ontology import (
    OntologyActionExecutePayload,
    OntologyActionTypePayload,
    OntologyAgentToolPayload,
    OntologyImportPayload,
    OntologyLinkPayload,
    OntologyLinkTypePayload,
    OntologyObjectPayload,
    OntologyObjectTypePayload,
    OntologyPublishPayload,
    OntologySyncPayload,
)
from app.models.user import PublicUser, is_model_editor_role, is_technical_role
from app.services.datasource_service import get_datasource_service
from app.services.ontology_mapping_preview_service import (
    get_ontology_mapping_preview_service,
)
from app.services.ontology_service import get_ontology_service
from app.services.permission_service import (
    domain_permission_not_configured_detail,
    get_permission_service,
)
from app.services.semantic_runtime import get_semantic_runtime_service
from app.services.twin_runtime_service import get_twin_runtime_service
from app.services.user_service import get_user_service

router = APIRouter()

ONTOLOGY_TECH_FIELD_DETAIL = "关联键、同步配置、动作授权和审批要求由技术人员维护"


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


def _non_empty_permission_value(value: Any) -> bool:
    return _canonical_permission_value(value) is not None


async def _existing_link_type(
    domain_id: int,
    payload: OntologyLinkTypePayload,
) -> dict[str, Any] | None:
    link_types = await get_ontology_service().list_link_types(domain_id)
    if payload.id:
        for item in link_types:
            if int(item.get("id") or 0) == int(payload.id):
                return dict(item)
    for item in link_types:
        if str(item.get("link_key") or "") == payload.link_key:
            return dict(item)
    return None


async def _default_relation_keys(
    domain_id: int,
    source_object_key: str,
    target_object_key: str,
) -> tuple[list[str], list[str]]:
    svc = get_ontology_service()
    source = await svc.get_object_type(domain_id, object_key=source_object_key)
    target = await svc.get_object_type(domain_id, object_key=target_object_key)
    return (
        [str(source.get("primary_property"))] if source else [],
        [str(target.get("primary_property"))] if target else [],
    )


def _link_payload_keys(payload: OntologyLinkTypePayload, side: str) -> list[str] | None:
    plural = getattr(payload, f"{side}_property_keys")
    singular = getattr(payload, f"{side}_property")
    if plural is not None:
        keys = [str(item).strip() for item in plural if str(item).strip()]
        return keys or None
    if singular:
        return [str(singular).strip()]
    return None


async def _prepare_link_type_for_role(
    domain_id: int,
    payload: OntologyLinkTypePayload,
    current_user: PublicUser,
) -> OntologyLinkTypePayload:
    if is_technical_role(current_user.role):
        return payload
    existing = await _existing_link_type(domain_id, payload)
    changed_fields: list[str] = []
    updates: dict[str, Any] = {}
    fields_set = getattr(payload, "model_fields_set", set())
    if existing:
        for field in ("link_key", "status"):
            if field in fields_set and str(getattr(payload, field)) != str(existing.get(field)):
                changed_fields.append(field)
            elif field not in fields_set and field in existing:
                updates[field] = existing[field]
    default_source_keys, default_target_keys = await _default_relation_keys(
        domain_id,
        payload.source_object_key,
        payload.target_object_key,
    )
    for side, default_keys in (("source", default_source_keys), ("target", default_target_keys)):
        keys = _link_payload_keys(payload, side)
        field_name = f"{side}_property_keys"
        singular_name = f"{side}_property"
        existing_keys = existing.get(field_name) if existing else None
        object_field = f"{side}_object_key"
        object_unchanged = bool(existing) and str(existing.get(object_field) or "") == str(
            getattr(payload, object_field) or ""
        )
        if keys is None:
            if existing_keys and object_unchanged:
                updates[field_name] = list(existing_keys)
                updates[singular_name] = existing_keys[0]
            continue
        if existing_keys and _permission_values_equal(keys, existing_keys):
            continue
        if not existing and _permission_values_equal(keys, default_keys):
            continue
        if existing and _permission_values_equal(keys, default_keys):
            continue
        changed_fields.append(field_name)
    if changed_fields:
        raise HTTPException(
            status_code=403,
            detail=f"{ONTOLOGY_TECH_FIELD_DETAIL}: {', '.join(changed_fields)}",
        )
    return payload.model_copy(update=updates) if updates else payload


async def _existing_action_type(
    domain_id: int, payload: OntologyActionTypePayload
) -> dict[str, Any] | None:
    action_types = await get_ontology_service().list_action_types(domain_id)
    if payload.id:
        for item in action_types:
            if int(item.get("id") or 0) == int(payload.id):
                return dict(item)
    for item in action_types:
        if str(item.get("action_key") or "") == payload.action_key:
            return dict(item)
    return None


async def _prepare_action_type_for_role(
    domain_id: int,
    payload: OntologyActionTypePayload,
    current_user: PublicUser,
) -> OntologyActionTypePayload:
    if is_technical_role(current_user.role):
        return payload
    existing = await _existing_action_type(domain_id, payload)
    updates: dict[str, Any] = {}
    changed_fields: list[str] = []
    fields_set = getattr(payload, "model_fields_set", set())
    for field, default in (
        ("allowed_roles", ["admin"]),
        ("requires_approval", False),
        ("action_key", None),
        ("status", "draft"),
    ):
        requested = getattr(payload, field)
        if existing and field not in fields_set:
            if field in existing:
                updates[field] = existing.get(field)
            continue
        if existing:
            if field != "action_key" and not _permission_values_equal(
                requested, existing.get(field)
            ):
                changed_fields.append(field)
            elif field == "action_key" and str(requested) != str(existing.get(field)):
                changed_fields.append(field)
        elif field in {"allowed_roles", "requires_approval", "status"} and not (
            _permission_values_equal(requested, default)
        ):
            changed_fields.append(field)
    if existing:
        existing_parameters = existing.get("parameters") or []
        requested_parameters = list(payload.parameters or [])
        for index, old_parameter in enumerate(existing_parameters[: len(requested_parameters)]):
            old_key = str((old_parameter or {}).get("parameter_key") or "")
            new_key = str(requested_parameters[index].parameter_key or "")
            if old_key and old_key != new_key:
                changed_fields.append(f"parameters[{index}].parameter_key")
        if "parameters" not in fields_set:
            updates["parameters"] = existing_parameters
    if changed_fields:
        raise HTTPException(
            status_code=403,
            detail=f"{ONTOLOGY_TECH_FIELD_DETAIL}: {', '.join(changed_fields)}",
        )
    return payload.model_copy(update=updates) if updates else payload


async def _assert_ontology_bundle_allowed_for_role(
    domain_id: int,
    bundle: dict[str, Any],
    current_user: PublicUser,
) -> None:
    if is_technical_role(current_user.role):
        return
    if not isinstance(bundle, dict):
        return
    object_types = bundle.get("object_types") or []
    link_types = bundle.get("link_types") or []
    action_types = bundle.get("action_types") or []
    if bundle.get("objects") or bundle.get("links"):
        raise HTTPException(
            status_code=403,
            detail="对象实例和关系实例属于技术运行数据，业务人员不能通过 Bundle 导入",
        )
    primary_by_object_key: dict[str, str] = {}
    try:
        for item in await get_ontology_service().list_object_types(domain_id):
            if item.get("object_key") and item.get("primary_property"):
                primary_by_object_key[str(item["object_key"])] = str(item["primary_property"])
    except ValueError:
        primary_by_object_key = {}
    for item in object_types:
        if not isinstance(item, dict):
            continue
        if item.get("object_key") and item.get("primary_property"):
            primary_by_object_key[str(item["object_key"])] = str(item["primary_property"])
        if bool(item.get("sync_enabled")) or _non_empty_permission_value(item.get("source_query")):
            raise HTTPException(
                status_code=403,
                detail=f"{ONTOLOGY_TECH_FIELD_DETAIL}: object_types.sync_enabled/source_query",
            )
        if item.get("sync_limit") not in (None, 200, "200"):
            raise HTTPException(
                status_code=403,
                detail=f"{ONTOLOGY_TECH_FIELD_DETAIL}: object_types.sync_limit",
            )
        if item.get("status") not in (None, "draft"):
            raise HTTPException(
                status_code=403,
                detail=f"{ONTOLOGY_TECH_FIELD_DETAIL}: object_types.status",
            )
    for item in link_types:
        if not isinstance(item, dict):
            continue
        source_primary = primary_by_object_key.get(str(item.get("source_object_key") or ""))
        target_primary = primary_by_object_key.get(str(item.get("target_object_key") or ""))
        source_defaults = [source_primary] if source_primary else []
        target_defaults = [target_primary] if target_primary else []
        for side, defaults in (("source", source_defaults), ("target", target_defaults)):
            keys = item.get(f"{side}_property_keys")
            if keys is None and item.get(f"{side}_property") is not None:
                keys = [item.get(f"{side}_property")]
            if isinstance(keys, list):
                keys = [str(value).strip() for value in keys if str(value).strip()]
            elif isinstance(keys, str) and not keys.strip():
                keys = None
            if keys is None:
                continue
            if not _permission_values_equal(keys, defaults):
                raise HTTPException(
                    status_code=403,
                    detail=f"{ONTOLOGY_TECH_FIELD_DETAIL}: link_types.{side}_property_keys",
                )
        if item.get("status") not in (None, "draft"):
            raise HTTPException(
                status_code=403,
                detail=f"{ONTOLOGY_TECH_FIELD_DETAIL}: link_types.status",
            )
    for item in action_types:
        if not isinstance(item, dict):
            continue
        if item.get("action_key") is not None and not str(item.get("action_key")).strip():
            raise HTTPException(
                status_code=403,
                detail=f"{ONTOLOGY_TECH_FIELD_DETAIL}: action_types.action_key",
            )
        for parameter in item.get("parameters") or []:
            if not isinstance(parameter, dict):
                continue
            if parameter.get("parameter_key") is None:
                continue
            if not str(parameter.get("parameter_key") or "").strip():
                raise HTTPException(
                    status_code=403,
                    detail=f"{ONTOLOGY_TECH_FIELD_DETAIL}: action_types.parameters.parameter_key",
                )
        if item.get("requires_approval") not in (None, False, 0):
            raise HTTPException(
                status_code=403,
                detail=f"{ONTOLOGY_TECH_FIELD_DETAIL}: action_types.requires_approval",
            )
        if "allowed_roles" in item and not _permission_values_equal(
            item.get("allowed_roles"), ["admin"]
        ):
            raise HTTPException(
                status_code=403,
                detail=f"{ONTOLOGY_TECH_FIELD_DETAIL}: action_types.allowed_roles",
            )
        if item.get("status") not in (None, "draft"):
            raise HTTPException(
                status_code=403,
                detail=f"{ONTOLOGY_TECH_FIELD_DETAIL}: action_types.status",
            )


@router.get("/domains")
async def list_accessible_domains(current_user: PublicUser = Depends(get_current_user)):
    """List Ontology domains visible to the current user.

    Business and technical product roles see company domains directly.  The
    legacy ``user`` role still resolves domains through validation-Agent grants.
    """
    svc = get_semantic_runtime_service()
    if is_model_editor_role(current_user.role):
        domains = await svc.list_all_domains()
    else:
        domains = []
        for agent_id in await get_user_service().get_user_agent_ids(current_user.id):
            domains.extend(await svc.list_domains(agent_id))
    seen: set[int] = set()
    visible = []
    for domain in domains:
        if int(domain.id) in seen:
            continue
        seen.add(int(domain.id))
        visible.append(domain.model_dump())
    return {"domains": visible}


def bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _resolve_data_access_agent(
    domain_id: int,
    access_agent_id: int | None,
) -> int | None:
    """Resolve an explicit permission subject for domain-backed data access."""
    runtime_service = get_semantic_runtime_service()
    domain = await runtime_service.get_domain(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="企业业务领域不存在")
    if domain.datasource_id is None:
        return None
    datasource_id = int(domain.datasource_id)
    permission_context = await get_permission_service().resolve_domain_permission_context(
        domain_id,
        datasource_id,
        compatibility_agent_id=access_agent_id,
        allow_agent_fallback=bool(access_agent_id),
    )
    if permission_context.source == "domain":
        return None
    if permission_context.source == "agent_compatibility":
        return access_agent_id
    return None


async def _data_permission_metadata(
    domain_id: int,
    compatibility_agent_id: int | None = None,
) -> dict | None:
    """Expose the resolved domain-first data permission subject to callers."""
    domain = await get_semantic_runtime_service().get_domain(domain_id)
    if domain is None or domain.datasource_id is None:
        return None
    context = await get_permission_service().resolve_domain_permission_context(
        domain_id,
        int(domain.datasource_id),
        compatibility_agent_id=compatibility_agent_id,
        allow_agent_fallback=bool(compatibility_agent_id),
    )
    return context.metadata()


async def _permission_http_error(
    domain_id: int, exc: PermissionError
) -> HTTPException:
    if "未配置数据权限" not in str(exc):
        return HTTPException(status_code=403, detail=str(exc))
    domain = await get_semantic_runtime_service().get_domain(domain_id)
    datasource_id = int(domain.datasource_id or 0) if domain is not None else 0
    return HTTPException(
        status_code=409,
        detail=domain_permission_not_configured_detail(domain_id, datasource_id),
    )


@router.get("/domains/{domain_id}/summary")
async def get_summary(domain_id: int, current_user: PublicUser = Depends(get_current_user)):
    await require_domain_access(domain_id, current_user)
    try:
        return await get_ontology_service().get_summary(domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/domains/{domain_id}/object-types")
async def list_object_types(
    domain_id: int,
    strict_release: bool = Query(
        default=False,
        description="运行时页面设为 true 时只返回 active release 定义",
    ),
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    try:
        service = get_ontology_service()
        if strict_release:
            definitions = await service.get_release_scoped_definitions(domain_id)
            return {"object_types": definitions["object_types"]}
        return {"object_types": await service.list_object_types(domain_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/domains/{domain_id}/object-types")
async def upsert_object_type(
    domain_id: int,
    payload: OntologyObjectTypePayload,
    current_user: PublicUser = Depends(require_model_editor),
):
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    if not is_technical_role(current_user.role):
        existing = (
            await get_ontology_service().get_object_type(domain_id, object_type_id=payload.id)
            if payload.id
            else None
        )
        if existing and str(payload.object_key) != str(existing.get("object_key")):
            raise HTTPException(
                status_code=403,
                detail="对象技术标识由技术人员维护",
            )
        if existing and str(payload.status) != str(existing.get("status")):
            raise HTTPException(
                status_code=403,
                detail="对象模型状态由技术人员维护",
            )
        if not existing and payload.status != "draft":
            raise HTTPException(
                status_code=403,
                detail="对象模型状态由技术人员维护，新建对象只能保存为草稿",
            )
        existing_query = str(existing.get("source_query") or "").strip() if existing else ""
        existing_sync = bool(existing.get("sync_enabled")) if existing else False
        existing_limit = int(existing.get("sync_limit") or 200) if existing else 200
        requested_query = payload.source_query.strip()
        if (
            payload.sync_enabled != existing_sync
            or requested_query != existing_query
            or int(payload.sync_limit) != existing_limit
            or (payload.sync_enabled and requested_query)
        ):
            raise HTTPException(
                status_code=403,
                detail="对象业务定义可以由业务人员维护，业务数据映射由技术人员维护",
            )
    try:
        item_id = await get_ontology_service().upsert_object_type(payload)
        return {"id": item_id, "message": "对象类型已保存"}
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.post("/domains/{domain_id}/object-types/mapping-preview")
async def preview_object_type_mapping(
    domain_id: int,
    payload: OntologyObjectTypePayload,
    current_user: PublicUser = Depends(require_model_editor),
):
    """Test an object source mapping without publishing or writing instances."""
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    if not is_technical_role(current_user.role):
        if payload.id is None:
            raise HTTPException(status_code=403, detail="业务人员只能预览已保存的数据绑定")
        saved = await get_ontology_service().get_object_type(
            domain_id,
            object_type_id=payload.id,
        )
        if saved is None:
            raise HTTPException(status_code=404, detail="对象类型不存在")
        # Business personnel may verify the persisted technical mapping, but
        # cannot submit an alternate SQL or permission-sensitive definition.
        payload = OntologyObjectTypePayload.model_validate(saved)
    # Keep the domain access check here so the endpoint cannot be used for a
    # foreign domain when the role model evolves.
    access_agent_id = await require_domain_access(domain_id, current_user)
    try:
        return await get_ontology_mapping_preview_service().preview(
            payload,
            access_agent_id=access_agent_id,
        )
    except PermissionError as exc:
        raise await _permission_http_error(domain_id, exc) from exc
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.delete("/domains/{domain_id}/object-types/{object_type_id}")
async def delete_object_type(
    domain_id: int, object_type_id: int, _: PublicUser = Depends(require_data_engineer)
):
    deleted = await get_ontology_service().delete_object_type(domain_id, object_type_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="对象类型不存在")
    return {"deleted": True, "id": object_type_id}


@router.get("/domains/{domain_id}/link-types")
async def list_link_types(
    domain_id: int,
    strict_release: bool = Query(
        default=False,
        description="运行时页面设为 true 时只返回 active release 定义",
    ),
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    try:
        service = get_ontology_service()
        if strict_release:
            definitions = await service.get_release_scoped_definitions(domain_id)
            return {"link_types": definitions["link_types"]}
        return {"link_types": await service.list_link_types(domain_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/domains/{domain_id}/link-types")
async def upsert_link_type(
    domain_id: int,
    payload: OntologyLinkTypePayload,
    current_user: PublicUser = Depends(require_model_editor),
):
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    payload = await _prepare_link_type_for_role(domain_id, payload, current_user)
    try:
        item_id = await get_ontology_service().upsert_link_type(payload)
        return {"id": item_id, "message": "关系类型已保存"}
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.delete("/domains/{domain_id}/link-types/{link_type_id}")
async def delete_link_type(
    domain_id: int, link_type_id: int, _: PublicUser = Depends(require_data_engineer)
):
    deleted = await get_ontology_service().delete_link_type(domain_id, link_type_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="关系类型不存在")
    return {"deleted": True, "id": link_type_id}


@router.get("/domains/{domain_id}/action-types")
async def list_action_types(
    domain_id: int,
    strict_release: bool = Query(
        default=False,
        description="运行时页面设为 true 时只返回 active release 定义",
    ),
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    try:
        service = get_ontology_service()
        if strict_release:
            definitions = await service.get_release_scoped_definitions(domain_id)
            return {"action_types": definitions["action_types"]}
        return {"action_types": await service.list_action_types(domain_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/domains/{domain_id}/agent-context")
async def get_agent_context(
    domain_id: int,
    current_user: PublicUser = Depends(get_current_user),
    strict_release: bool = Query(
        default=False,
        description="运行时页面设为 true 时只允许使用当前激活企业模型版本",
    ),
):
    """Return role-filtered Ontology context and bounded runtime tools.

    The application context includes object-query, read-only Query Capability,
    and published Action definitions.
    """
    await require_domain_access(domain_id, current_user)
    try:
        context, runtime = await _load_query_runtime_context(
            get_ontology_service(),
            domain_id,
            current_user.model_dump(),
            require_active_release=strict_release,
        )
    except ValueError as exc:
        # A strict runtime without an active release is a domain state conflict,
        # not an unhandled server error.  The UI can use this to guide the user
        # back to model validation and activation.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        **context,
        "query_capabilities": build_query_capability_definitions(runtime, context),
        "tools": build_ontology_tool_definitions(include_query_capability=True),
    }


@router.get("/domains/{domain_id}/query-capabilities")
async def list_query_capabilities(
    domain_id: int,
    current_user: PublicUser = Depends(get_current_user),
):
    """Return the read-only Query Capability contracts available in a domain."""
    await require_domain_access(domain_id, current_user)
    context, runtime = await _load_query_runtime_context(
        get_ontology_service(),
        domain_id,
        current_user.model_dump(),
    )
    return {
        "query_capabilities": build_query_capability_definitions(runtime, context),
    }


@router.get("/domains/{domain_id}/query")
async def query_objects(
    domain_id: int,
    object_type_key: str | None = Query(default=None, max_length=128),
    search: str | None = Query(default=None, max_length=256),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: PublicUser = Depends(get_current_user),
):
    """Search active Ontology objects for an application or Agent."""
    access_agent_id = await require_domain_access(domain_id, current_user)
    permission_agent_id = await _resolve_data_access_agent(domain_id, access_agent_id)
    try:
        return await get_ontology_service().query_objects(
            domain_id,
            access_agent_id=permission_agent_id,
            object_type_key=object_type_key,
            search=search,
            limit=limit,
            offset=offset,
        )
    except PermissionError as exc:
        raise await _permission_http_error(domain_id, exc) from exc
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.post("/domains/{domain_id}/agent-tools/{tool_name}")
async def run_agent_tool(
    domain_id: int,
    tool_name: str,
    payload: OntologyAgentToolPayload,
    current_user: PublicUser = Depends(get_current_user),
):
    """Invoke one bounded Ontology runtime tool.

    For ``ontology_query_capability``, the domain must have a non-null
    datasource accessible to the selected consumer Agent.  The independent v1 Query path executes
    read-only SQL directly after validation and deterministic compilation; it
    does not use the Chat graph's SQL-confirmation checkpoint.  Object query
    and published Action behavior retain their existing boundaries.
    """
    access_agent_id = await require_domain_access(domain_id, current_user)
    try:
        permission_agent_id = None
        if tool_name in {QUERY_TOOL, ACTION_TOOL}:
            permission_agent_id = await _resolve_data_access_agent(
                domain_id, access_agent_id
            )
        if tool_name == QUERY_TOOL:
            args = dict(payload.arguments or {})
            allowed = {"object_type_key", "search", "limit", "offset"}
            unknown = sorted(set(args) - allowed)
            if unknown:
                raise ValueError(f"对象查询工具包含未知参数: {', '.join(unknown)}")
            return await get_ontology_service().query_objects(
                domain_id,
                access_agent_id=permission_agent_id,
                object_type_key=args.get("object_type_key"),
                search=args.get("search"),
                limit=args.get("limit", 20),
                offset=args.get("offset", 0),
            )
        query_context: dict[str, object] = {}
        if tool_name == QUERY_CAPABILITY_TOOL:
            context, runtime = await _load_query_runtime_context(
                get_ontology_service(),
                domain_id,
                current_user.model_dump(),
            )
            datasource_id = runtime.domain.datasource_id
            if datasource_id is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Query Capability 未绑定 datasource_id，"
                        "拒绝回退到默认 business DB"
                    ),
                )
            execution_agent_id = await _resolve_data_access_agent(
                domain_id, access_agent_id
            )
            if execution_agent_id is not None:
                runtime.domain.agent_id = execution_agent_id
                if not await get_datasource_service().belongs_to_agent(
                    datasource_id,
                    execution_agent_id,
                ):
                    raise HTTPException(
                        status_code=403,
                        detail="兼容权限智能体无权访问该数据源",
                    )
            context["data_permission"] = await _data_permission_metadata(
                domain_id, execution_agent_id
            )
            query_context = {
                "ontology_context": context,
                "semantic_runtime": runtime,
            }
        return await invoke_ontology_tool(
            get_ontology_service(),
            domain_id,
            tool_name,
            payload.arguments,
            current_user.model_dump(),
            access_agent_id=permission_agent_id,
            **query_context,
        )
    except PermissionError as exc:
        raise await _permission_http_error(domain_id, exc) from exc
    except ValueError as exc:
        raise bad_request(exc) from exc
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.post("/domains/{domain_id}/action-types")
async def upsert_action_type(
    domain_id: int,
    payload: OntologyActionTypePayload,
    current_user: PublicUser = Depends(require_model_editor),
):
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    payload = await _prepare_action_type_for_role(domain_id, payload, current_user)
    try:
        item_id = await get_ontology_service().upsert_action_type(payload)
        return {"id": item_id, "message": "动作类型已保存"}
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.delete("/domains/{domain_id}/action-types/{action_type_id}")
async def delete_action_type(
    domain_id: int, action_type_id: int, _: PublicUser = Depends(require_data_engineer)
):
    deleted = await get_ontology_service().delete_action_type(domain_id, action_type_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="动作类型不存在")
    return {"deleted": True, "id": action_type_id}


@router.post("/domains/{domain_id}/validate")
async def validate_domain(domain_id: int, _: PublicUser = Depends(require_model_editor)):
    try:
        return await get_ontology_service().validate_domain(domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/domains/{domain_id}/publish")
async def publish_domain(
    domain_id: int,
    payload: OntologyPublishPayload,
    current_user: PublicUser = Depends(require_model_publisher),
):
    try:
        result = await get_ontology_service().publish_domain(
            domain_id,
            current_user.id,
            name=payload.name,
            description=payload.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not result["published"]:
        raise HTTPException(status_code=422, detail=result["validation"])
    return result


@router.get("/domains/{domain_id}/releases")
async def list_releases(domain_id: int, current_user: PublicUser = Depends(get_current_user)):
    await require_domain_access(domain_id, current_user)
    return {"releases": await get_ontology_service().list_releases(domain_id)}


@router.get("/domains/{domain_id}/export")
async def export_bundle(
    domain_id: int,
    include_instances: bool = True,
    _: PublicUser = Depends(require_model_editor),
):
    try:
        return await get_ontology_service().export_bundle(domain_id, include_instances)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/domains/{domain_id}/import")
async def import_bundle(
    domain_id: int,
    payload: OntologyImportPayload,
    current_user: PublicUser = Depends(require_model_editor),
):
    try:
        if not is_technical_role(current_user.role) and payload.replace:
            raise HTTPException(
                status_code=403,
                detail="业务人员不能使用替换导入；如需清空并重建模型，请由技术人员操作",
            )
        await _assert_ontology_bundle_allowed_for_role(domain_id, payload.bundle, current_user)
        counts = await get_ontology_service().import_bundle(
            domain_id, payload.bundle, replace=payload.replace
        )
        return {"imported": counts, "message": "Ontology bundle 已导入"}
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.post("/domains/{domain_id}/sync")
async def sync_objects_from_datasource(
    domain_id: int,
    payload: OntologySyncPayload,
    current_user: PublicUser = Depends(get_current_user),
):
    """Compatibility adapter for governed twin-runtime write synchronization."""
    if not is_technical_role(current_user.role):
        raise HTTPException(status_code=403, detail="只有技术人员可以启动写入型孪生同步")
    access_agent_id = await require_domain_access(domain_id, current_user)
    permission_agent_id = await _resolve_data_access_agent(domain_id, access_agent_id)
    try:
        response = await get_twin_runtime_service().execute_sync(
            domain_id=domain_id,
            access_agent_id=permission_agent_id,
            created_by=current_user.id,
            object_type_id=payload.object_type_id,
            page=payload.page,
            page_size=payload.page_size,
            sync_links=payload.sync_links,
            dry_run=False,
            trace_id=None,
        )
        return response["result"]
    except PermissionError as exc:
        raise await _permission_http_error(domain_id, exc) from exc
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.get("/domains/{domain_id}/objects")
async def list_objects(
    domain_id: int,
    object_type_id: int | None = None,
    limit: int = Query(default=1000, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    strict_release: bool = Query(
        default=False,
        description="运行时页面设为 true 时只读取 active release 对象定义",
    ),
    current_user: PublicUser = Depends(get_current_user),
):
    access_agent_id = await require_domain_access(domain_id, current_user)
    permission_agent_id = await _resolve_data_access_agent(domain_id, access_agent_id)
    try:
        service = get_ontology_service()
        release_definition = (
            await service.get_release_scoped_definitions(domain_id)
            if strict_release
            else None
        )
        return {
            "objects": await service.list_objects(
                domain_id,
                object_type_id,
                limit=limit,
                offset=offset,
                access_agent_id=permission_agent_id,
                release_definition=release_definition,
            ),
            "permission": await _data_permission_metadata(
                domain_id, permission_agent_id
            ),
        }
    except PermissionError as exc:
        raise await _permission_http_error(domain_id, exc) from exc
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.post("/domains/{domain_id}/objects")
async def upsert_object(
    domain_id: int,
    payload: OntologyObjectPayload,
    _: PublicUser = Depends(require_data_engineer),
):
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    try:
        item_id = await get_ontology_service().upsert_object(payload)
        return {"id": item_id, "message": "对象实例已保存"}
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.delete("/domains/{domain_id}/objects/{object_id}")
async def delete_object(
    domain_id: int,
    object_id: int,
    _: PublicUser = Depends(require_data_engineer),
):
    deleted = await get_ontology_service().delete_object(domain_id, object_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="对象实例不存在")
    return {"deleted": True, "id": object_id}


@router.get("/domains/{domain_id}/links")
async def list_links(
    domain_id: int,
    strict_release: bool = Query(
        default=False,
        description="运行时页面设为 true 时只读取 active release 关系定义",
    ),
    current_user: PublicUser = Depends(get_current_user),
):
    access_agent_id = await require_domain_access(domain_id, current_user)
    permission_agent_id = await _resolve_data_access_agent(domain_id, access_agent_id)
    try:
        service = get_ontology_service()
        release_definition = (
            await service.get_release_scoped_definitions(domain_id)
            if strict_release
            else None
        )
        links = await service.list_links(
            domain_id,
            access_agent_id=permission_agent_id,
            release_definition=release_definition,
        )
    except PermissionError as exc:
        raise await _permission_http_error(domain_id, exc) from exc
    except ValueError as exc:
        raise bad_request(exc) from exc
    return {
        "links": links,
        "permission": await _data_permission_metadata(domain_id, permission_agent_id),
    }


@router.post("/domains/{domain_id}/links")
async def create_link(
    domain_id: int,
    payload: OntologyLinkPayload,
    _: PublicUser = Depends(require_data_engineer),
):
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    try:
        item_id = await get_ontology_service().create_link(payload)
        return {"id": item_id, "message": "关系实例已保存"}
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.delete("/domains/{domain_id}/links/{link_id}")
async def delete_link(domain_id: int, link_id: int, _: PublicUser = Depends(require_data_engineer)):
    deleted = await get_ontology_service().delete_link(domain_id, link_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="关系实例不存在")
    return {"deleted": True, "id": link_id}


@router.post("/domains/{domain_id}/actions/{action_type_id}/execute")
async def execute_action(
    domain_id: int,
    action_type_id: int,
    payload: OntologyActionExecutePayload,
    current_user: PublicUser = Depends(get_current_user),
):
    access_agent_id = await require_domain_access(domain_id, current_user)
    permission_agent_id = await _resolve_data_access_agent(domain_id, access_agent_id)
    try:
        return await get_ontology_service().execute_action(
            domain_id,
            action_type_id,
            payload,
            current_user.model_dump(),
            access_agent_id=permission_agent_id,
        )
    except PermissionError as exc:
        raise await _permission_http_error(domain_id, exc) from exc
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.get("/domains/{domain_id}/action-runs")
async def list_action_runs(
    domain_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    strict_release: bool = Query(
        default=False,
        description="运行时页面设为 true 时只读取 active release 动作定义",
    ),
    current_user: PublicUser = Depends(get_current_user),
):
    access_agent_id = await require_domain_access(domain_id, current_user)
    permission_agent_id = await _resolve_data_access_agent(domain_id, access_agent_id)
    user_id = None if is_technical_role(current_user.role) else current_user.id
    try:
        service = get_ontology_service()
        release_definition = (
            await service.get_release_scoped_definitions(domain_id)
            if strict_release
            else None
        )
        runs = await service.list_action_runs(
            domain_id,
            user_id=user_id,
            limit=limit,
            access_agent_id=permission_agent_id,
            release_definition=release_definition,
        )
    except PermissionError as exc:
        raise await _permission_http_error(domain_id, exc) from exc
    except ValueError as exc:
        raise bad_request(exc) from exc
    return {
        "runs": runs,
        "permission": await _data_permission_metadata(domain_id, permission_agent_id),
    }
