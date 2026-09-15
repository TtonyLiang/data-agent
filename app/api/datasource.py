"""数据源管理 API —— 业务库连接配置的 CRUD、表采集与连通性测试。

所有操作委托给 DatasourceService 和 MetadataService。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user, require_data_engineer, require_domain_access
from app.db.mysql import get_management_db
from app.models.datasource import DatasourceCreate, DatasourceUpdate
from app.models.permission import DatasourcePermissionReplace
from app.models.user import PublicUser
from app.services.datasource_service import get_datasource_service
from app.services.metadata_service import get_metadata_service
from app.services.permission_service import get_permission_service
from app.services.semantic_runtime import get_semantic_runtime_service

logger = logging.getLogger(__name__)
router = APIRouter()


async def _validate_permission_scope(ds_id: int, agent_id: int) -> None:
    agent_rows = await get_management_db().execute_query(
        "SELECT id FROM agent WHERE id = :agent_id",
        {"agent_id": agent_id},
    )
    if not agent_rows:
        raise HTTPException(status_code=404, detail="智能体不存在")
    datasource_service = get_datasource_service()
    if await datasource_service.get(ds_id) is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    if not await datasource_service.belongs_to_agent(ds_id, agent_id):
        raise HTTPException(status_code=400, detail="智能体与数据源尚未绑定")


async def _validate_domain_permission_scope(ds_id: int, domain_id: int) -> None:
    domain = await get_semantic_runtime_service().get_domain(domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="业务领域不存在")
    if await get_datasource_service().get(ds_id) is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    if int(domain.datasource_id or 0) != ds_id:
        raise HTTPException(status_code=400, detail="业务领域未绑定当前数据源")


async def _validate_permission_rules(
    ds_id: int, request: DatasourcePermissionReplace
) -> None:
    schema = await get_metadata_service().get_schema(ds_id)
    columns_by_table = {
        str(table.get("table_name") or "").lower(): {
            str(column.get("column_name") or "").lower()
            for column in table.get("columns") or []
        }
        for table in schema
        if table.get("table_name")
    }
    unknown_tables = sorted(
        {
            rule.table_name
            for rule in request.table_permissions
            if rule.table_name.lower() not in columns_by_table
        }
        | {
            rule.table_name
            for rule in request.column_permissions
            if rule.table_name.lower() not in columns_by_table
        }
    )
    if unknown_tables:
        raise HTTPException(
            status_code=400,
            detail="表不存在或尚未采集: " + "、".join(unknown_tables),
        )
    unknown_columns = sorted(
        f"{rule.table_name}.{rule.column_name}"
        for rule in request.column_permissions
        if rule.column_name.lower()
        not in columns_by_table.get(rule.table_name.lower(), set())
    )
    if unknown_columns:
        raise HTTPException(
            status_code=400,
            detail="字段不存在或尚未采集: " + "、".join(unknown_columns),
        )


@router.post("/create", dependencies=[Depends(require_data_engineer)])
async def create_datasource(ds: DatasourceCreate):
    """创建数据源。"""
    svc = get_datasource_service()
    ds_id = await svc.create(ds)
    return {"id": ds_id, "message": "数据源创建成功"}


@router.get("/list/{agent_id}")
async def list_datasources(agent_id: int, _: PublicUser = Depends(require_data_engineer)):
    """列出指定智能体绑定的数据源(管理页面用,不含密码)。"""
    svc = get_datasource_service()
    ds_list = await svc.list_by_agent(agent_id)
    return {"datasources": [ds.model_dump(exclude={"password"}) for ds in ds_list]}


@router.get("/list")
async def list_all_datasources(_: PublicUser = Depends(require_data_engineer)):
    """列出所有数据源(管理页面用)。"""
    svc = get_datasource_service()
    ds_list = await svc.list_all()
    return {"datasources": [ds.model_dump(exclude={"password"}) for ds in ds_list]}


@router.get("/agent/{agent_id}/ids")
async def list_agent_datasource_ids(agent_id: int, _: PublicUser = Depends(require_data_engineer)):
    """获取指定智能体绑定的数据源 id 列表。"""
    ids = await get_datasource_service().get_agent_datasource_ids(agent_id)
    return {"datasource_ids": ids}


@router.put("/agent/{agent_id}/ids")
async def update_agent_datasource_ids(
    agent_id: int,
    request: dict,
    _: PublicUser = Depends(require_data_engineer),
):
    """替换指定智能体的数据源绑定集合。"""
    ids = await get_datasource_service().set_agent_datasources(
        agent_id,
        request.get("datasource_ids", []),
    )
    return {"datasource_ids": ids, "message": "关联已保存"}


@router.get("/{ds_id}/permissions/{agent_id}")
async def get_datasource_permissions(
    ds_id: int,
    agent_id: int,
    _: PublicUser = Depends(require_data_engineer),
):
    """查看指定智能体在该数据源上的显式表/列权限规则。"""
    await _validate_permission_scope(ds_id, agent_id)
    configuration = await get_permission_service().get_permission_configuration(agent_id, ds_id)
    return {"permissions": configuration.model_dump()}


@router.put("/{ds_id}/permissions/{agent_id}")
async def replace_datasource_permissions(
    ds_id: int,
    agent_id: int,
    request: DatasourcePermissionReplace,
    _: PublicUser = Depends(require_data_engineer),
):
    """完整替换指定智能体在该数据源上的表/列权限规则。"""
    await _validate_permission_scope(ds_id, agent_id)
    await _validate_permission_rules(ds_id, request)
    configuration = await get_permission_service().replace_permission_configuration(
        agent_id,
        ds_id,
        request,
    )
    return {"permissions": configuration.model_dump(), "message": "访问权限已保存"}


@router.get("/{ds_id}/domain-permissions/{domain_id}")
async def get_domain_datasource_permissions(
    ds_id: int,
    domain_id: int,
    _: PublicUser = Depends(require_data_engineer),
):
    """查看业务领域在该数据源上的正式表/列权限规则。"""
    await _validate_domain_permission_scope(ds_id, domain_id)
    configuration = (
        await get_permission_service().get_domain_permission_configuration(
            domain_id, ds_id
        )
    )
    return {"permissions": configuration.model_dump()}


@router.put("/{ds_id}/domain-permissions/{domain_id}")
async def replace_domain_datasource_permissions(
    ds_id: int,
    domain_id: int,
    request: DatasourcePermissionReplace,
    _: PublicUser = Depends(require_data_engineer),
):
    """完整替换业务领域在该数据源上的表/列权限规则。"""
    await _validate_domain_permission_scope(ds_id, domain_id)
    await _validate_permission_rules(ds_id, request)
    configuration = (
        await get_permission_service().replace_domain_permission_configuration(
            domain_id,
            ds_id,
            request,
        )
    )
    return {"permissions": configuration.model_dump(), "message": "领域访问权限已保存"}


@router.put("/{ds_id}")
async def update_datasource(
    ds_id: int,
    ds: DatasourceUpdate,
    _: PublicUser = Depends(require_data_engineer),
):
    """更新数据源配置。密码为空或掩码时保留原值。"""
    svc = get_datasource_service()
    updated = await svc.update(ds_id, ds)
    if updated is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return {
        "datasource": updated.model_dump(exclude={"password"}),
        "message": "更新成功",
    }


@router.delete("/{ds_id}")
async def delete_datasource(ds_id: int, _: PublicUser = Depends(require_data_engineer)):
    """删除数据源及其关联的全部语义层资产与采集元数据。"""
    svc = get_datasource_service()
    try:
        await svc.delete(ds_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"message": "删除成功"}


@router.post("/{ds_id}/test")
async def test_connection(ds_id: int, _: PublicUser = Depends(require_data_engineer)):
    """测试数据源连通性(SELECT 1)。"""
    svc = get_datasource_service()
    ok = await svc.test_connection(ds_id)
    return {"success": ok, "message": "连接成功" if ok else "连接失败"}


@router.post("/{ds_id}/collect-schema")
async def collect_schema(
    ds_id: int,
    request: dict | None = None,
    _: PublicUser = Depends(require_data_engineer),
):
    """采集指定表的元数据。table_names 为空时采集全部。"""
    meta_svc = get_metadata_service()
    table_names = None
    if request is not None and "table_names" in request:
        table_names = request.get("table_names") or []
    result = await meta_svc.collect_schema(ds_id, table_names=table_names)
    return {"tables": result, "message": f"采集完成，共 {len(result)} 张表"}


@router.post("/{ds_id}/uncollect-schema")
async def uncollect_schema(
    ds_id: int,
    request: dict | None = None,
    _: PublicUser = Depends(require_data_engineer),
):
    """取消采集指定表。"""
    meta_svc = get_metadata_service()
    table_names = []
    if request is not None and "table_names" in request:
        table_names = request.get("table_names") or []
    result = await meta_svc.uncollect_schema(ds_id, table_names=table_names)
    return {"tables": result, "message": f"已取消采集 {len(result)} 张表"}


@router.get("/{ds_id}/remote-tables")
async def list_remote_tables(ds_id: int, _: PublicUser = Depends(require_data_engineer)):
    """从业务库读取全部表清单(含采集状态)。"""
    meta_svc = get_metadata_service()
    tables = await meta_svc.list_remote_tables(ds_id)
    return {"tables": tables}


@router.get("/{ds_id}/schema/tables")
async def get_collected_table_summaries(ds_id: int, _: PublicUser = Depends(require_data_engineer)):
    """获取已采集表列表(不含字段明细)。"""
    meta_svc = get_metadata_service()
    tables = await meta_svc.get_table_summaries(ds_id)
    return {"tables": tables}


@router.get("/{ds_id}/schema/stats")
async def get_collected_schema_stats(ds_id: int, _: PublicUser = Depends(require_data_engineer)):
    """获取已采集 schema 的统计信息(表数、字段数、噪音等级)。"""
    meta_svc = get_metadata_service()
    return {"stats": await meta_svc.get_schema_stats(ds_id)}


@router.get("/{ds_id}/schema/tables/{table_id}")
async def get_collected_table_detail(
    ds_id: int,
    table_id: int,
    _: PublicUser = Depends(require_data_engineer),
):
    """获取单张表的详细信息(含字段列表)。"""
    meta_svc = get_metadata_service()
    table = await meta_svc.get_table_detail(ds_id, table_id)
    if table is None:
        raise HTTPException(status_code=404, detail="表结构不存在")
    return {"table": table}


@router.get("/{ds_id}/schema")
async def get_collected_schema(
    ds_id: int,
    domain_id: int | None = Query(default=None, gt=0),
    current_user: PublicUser = Depends(get_current_user),
):
    """获取已采集 schema；业务领域读取必须经过领域表/列权限过滤。"""
    meta_svc = get_metadata_service()
    if domain_id is None:
        await require_data_engineer(current_user)
        tables = await meta_svc.get_schema(ds_id)
        return {"tables": tables}

    await require_domain_access(domain_id, current_user)
    await _validate_domain_permission_scope(ds_id, domain_id)
    tables = await meta_svc.get_authorized_schema(
        ds_id,
        domain_id=domain_id,
        allow_agent_fallback=False,
    )
    return {"tables": tables}
