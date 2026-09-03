"""REST API for business Ontology definition, publishing, runtime, and audit."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agent.ontology_tools import (
    QUERY_CAPABILITY_TOOL,
    _load_query_runtime_context,
    build_ontology_tool_definitions,
    build_query_capability_definitions,
    invoke_ontology_tool,
)
from app.api.deps import get_current_user, require_admin, require_domain_access
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
from app.models.user import PublicUser
from app.services.datasource_service import get_datasource_service
from app.services.ontology_service import get_ontology_service
from app.services.semantic_runtime import get_semantic_runtime_service
from app.services.user_service import get_user_service

router = APIRouter()


@router.get("/domains")
async def list_accessible_domains(current_user: PublicUser = Depends(get_current_user)):
    """List Ontology domains visible to the current user.

    Administrators see all domains; business users see domains consumable by
    an Agent explicitly granted through ``user_agent_permission``.
    """
    svc = get_semantic_runtime_service()
    if current_user.role == "admin":
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


@router.get("/domains/{domain_id}/summary")
async def get_summary(domain_id: int, current_user: PublicUser = Depends(get_current_user)):
    await require_domain_access(domain_id, current_user)
    try:
        return await get_ontology_service().get_summary(domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/domains/{domain_id}/object-types")
async def list_object_types(domain_id: int, current_user: PublicUser = Depends(get_current_user)):
    await require_domain_access(domain_id, current_user)
    try:
        return {"object_types": await get_ontology_service().list_object_types(domain_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/domains/{domain_id}/object-types")
async def upsert_object_type(
    domain_id: int,
    payload: OntologyObjectTypePayload,
    _: PublicUser = Depends(require_admin),
):
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    try:
        item_id = await get_ontology_service().upsert_object_type(payload)
        return {"id": item_id, "message": "对象类型已保存"}
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.delete("/domains/{domain_id}/object-types/{object_type_id}")
async def delete_object_type(
    domain_id: int, object_type_id: int, _: PublicUser = Depends(require_admin)
):
    deleted = await get_ontology_service().delete_object_type(domain_id, object_type_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="对象类型不存在")
    return {"deleted": True, "id": object_type_id}


@router.get("/domains/{domain_id}/link-types")
async def list_link_types(domain_id: int, current_user: PublicUser = Depends(get_current_user)):
    await require_domain_access(domain_id, current_user)
    try:
        return {"link_types": await get_ontology_service().list_link_types(domain_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/domains/{domain_id}/link-types")
async def upsert_link_type(
    domain_id: int,
    payload: OntologyLinkTypePayload,
    _: PublicUser = Depends(require_admin),
):
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    try:
        item_id = await get_ontology_service().upsert_link_type(payload)
        return {"id": item_id, "message": "关系类型已保存"}
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.delete("/domains/{domain_id}/link-types/{link_type_id}")
async def delete_link_type(
    domain_id: int, link_type_id: int, _: PublicUser = Depends(require_admin)
):
    deleted = await get_ontology_service().delete_link_type(domain_id, link_type_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="关系类型不存在")
    return {"deleted": True, "id": link_type_id}


@router.get("/domains/{domain_id}/action-types")
async def list_action_types(domain_id: int, current_user: PublicUser = Depends(get_current_user)):
    await require_domain_access(domain_id, current_user)
    return {"action_types": await get_ontology_service().list_action_types(domain_id)}


@router.get("/domains/{domain_id}/agent-context")
async def get_agent_context(domain_id: int, current_user: PublicUser = Depends(get_current_user)):
    """Return role-filtered Ontology context and bounded runtime tools.

    The application context includes object-query, read-only Query Capability,
    and published Action definitions.
    """
    await require_domain_access(domain_id, current_user)
    context, runtime = await _load_query_runtime_context(
        get_ontology_service(),
        domain_id,
        current_user.model_dump(),
    )
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
    await require_domain_access(domain_id, current_user)
    return await get_ontology_service().query_objects(
        domain_id,
        object_type_key=object_type_key,
        search=search,
        limit=limit,
        offset=offset,
    )


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
            runtime_service = get_semantic_runtime_service()
            preferred_agent_id = runtime.domain.agent_id
            if isinstance(access_agent_id, int):
                execution_agent_id = access_agent_id
            elif current_user.role == "admin":
                execution_agent_id = await runtime_service.resolve_domain_agent(
                    domain_id,
                    preferred_agent_id,
                )
            else:
                # Compatibility for direct function callers/tests that replace
                # the access dependency without returning its resolved Agent.
                execution_agent_id = preferred_agent_id
            if execution_agent_id is None:
                raise HTTPException(status_code=403, detail="领域尚未绑定当前用户可用的智能体")
            runtime.domain.agent_id = execution_agent_id
            if not await get_datasource_service().belongs_to_agent(
                datasource_id,
                execution_agent_id,
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Query Capability 无权访问该数据源",
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
            **query_context,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.post("/domains/{domain_id}/action-types")
async def upsert_action_type(
    domain_id: int,
    payload: OntologyActionTypePayload,
    _: PublicUser = Depends(require_admin),
):
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    try:
        item_id = await get_ontology_service().upsert_action_type(payload)
        return {"id": item_id, "message": "动作类型已保存"}
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.delete("/domains/{domain_id}/action-types/{action_type_id}")
async def delete_action_type(
    domain_id: int, action_type_id: int, _: PublicUser = Depends(require_admin)
):
    deleted = await get_ontology_service().delete_action_type(domain_id, action_type_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="动作类型不存在")
    return {"deleted": True, "id": action_type_id}


@router.post("/domains/{domain_id}/validate")
async def validate_domain(domain_id: int, _: PublicUser = Depends(require_admin)):
    try:
        return await get_ontology_service().validate_domain(domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/domains/{domain_id}/publish")
async def publish_domain(
    domain_id: int,
    payload: OntologyPublishPayload,
    current_user: PublicUser = Depends(require_admin),
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
    _: PublicUser = Depends(require_admin),
):
    try:
        return await get_ontology_service().export_bundle(domain_id, include_instances)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/domains/{domain_id}/import")
async def import_bundle(
    domain_id: int,
    payload: OntologyImportPayload,
    _: PublicUser = Depends(require_admin),
):
    try:
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
    """Read one source page and merge it with local Ontology action overlays."""
    await require_domain_access(domain_id, current_user)
    try:
        return await get_ontology_service().sync_objects_from_datasource(
            domain_id,
            object_type_id=payload.object_type_id,
            page=payload.page,
            page_size=payload.page_size,
            sync_links=payload.sync_links,
        )
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.get("/domains/{domain_id}/objects")
async def list_objects(
    domain_id: int,
    object_type_id: int | None = None,
    limit: int = Query(default=1000, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    return {
        "objects": await get_ontology_service().list_objects(
            domain_id, object_type_id, limit=limit, offset=offset
        )
    }


@router.post("/domains/{domain_id}/objects")
async def upsert_object(
    domain_id: int,
    payload: OntologyObjectPayload,
    _: PublicUser = Depends(require_admin),
):
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    try:
        item_id = await get_ontology_service().upsert_object(payload)
        return {"id": item_id, "message": "对象实例已保存"}
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.delete("/domains/{domain_id}/objects/{object_id}")
async def delete_object(domain_id: int, object_id: int, _: PublicUser = Depends(require_admin)):
    deleted = await get_ontology_service().delete_object(domain_id, object_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="对象实例不存在")
    return {"deleted": True, "id": object_id}


@router.get("/domains/{domain_id}/links")
async def list_links(domain_id: int, current_user: PublicUser = Depends(get_current_user)):
    await require_domain_access(domain_id, current_user)
    return {"links": await get_ontology_service().list_links(domain_id)}


@router.post("/domains/{domain_id}/links")
async def create_link(
    domain_id: int,
    payload: OntologyLinkPayload,
    _: PublicUser = Depends(require_admin),
):
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    try:
        item_id = await get_ontology_service().create_link(payload)
        return {"id": item_id, "message": "关系实例已保存"}
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.delete("/domains/{domain_id}/links/{link_id}")
async def delete_link(domain_id: int, link_id: int, _: PublicUser = Depends(require_admin)):
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
    await require_domain_access(domain_id, current_user)
    try:
        return await get_ontology_service().execute_action(
            domain_id, action_type_id, payload, current_user.model_dump()
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise bad_request(exc) from exc


@router.get("/domains/{domain_id}/action-runs")
async def list_action_runs(
    domain_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    user_id = None if current_user.role == "admin" else current_user.id
    return {
        "runs": await get_ontology_service().list_action_runs(
            domain_id, user_id=user_id, limit=limit
        )
    }
