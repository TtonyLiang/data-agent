from fastapi import APIRouter, HTTPException

from app.models.datasource import DatasourceCreate, DatasourceUpdate
from app.services.datasource_service import get_datasource_service
from app.services.metadata_service import get_metadata_service

router = APIRouter()


@router.post("/create")
async def create_datasource(ds: DatasourceCreate):
    svc = get_datasource_service()
    ds_id = await svc.create(ds)
    return {"id": ds_id, "message": "数据源创建成功"}


@router.get("/list/{agent_id}")
async def list_datasources(agent_id: int):
    svc = get_datasource_service()
    ds_list = await svc.list_by_agent(agent_id)
    return {"datasources": [ds.model_dump(exclude={"password"}) for ds in ds_list]}


@router.get("/list")
async def list_all_datasources():
    svc = get_datasource_service()
    ds_list = await svc.list_all()
    return {"datasources": [ds.model_dump(exclude={"password"}) for ds in ds_list]}


@router.get("/agent/{agent_id}/ids")
async def list_agent_datasource_ids(agent_id: int):
    ids = await get_datasource_service().get_agent_datasource_ids(agent_id)
    return {"datasource_ids": ids}


@router.put("/agent/{agent_id}/ids")
async def update_agent_datasource_ids(agent_id: int, request: dict):
    ids = await get_datasource_service().set_agent_datasources(
        agent_id,
        request.get("datasource_ids", []),
    )
    return {"datasource_ids": ids, "message": "关联已保存"}


@router.put("/{ds_id}")
async def update_datasource(ds_id: int, ds: DatasourceUpdate):
    svc = get_datasource_service()
    updated = await svc.update(ds_id, ds)
    if updated is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return {
        "datasource": updated.model_dump(exclude={"password"}),
        "message": "更新成功",
    }


@router.delete("/{ds_id}")
async def delete_datasource(ds_id: int):
    svc = get_datasource_service()
    await svc.delete(ds_id)
    return {"message": "删除成功"}


@router.post("/{ds_id}/test")
async def test_connection(ds_id: int):
    svc = get_datasource_service()
    ok = await svc.test_connection(ds_id)
    return {"success": ok, "message": "连接成功" if ok else "连接失败"}


@router.post("/{ds_id}/collect-schema")
async def collect_schema(ds_id: int, request: dict | None = None):
    meta_svc = get_metadata_service()
    table_names = None
    if request is not None and "table_names" in request:
        table_names = request.get("table_names") or []
    result = await meta_svc.collect_schema(ds_id, table_names=table_names)
    return {"tables": result, "message": f"采集完成，共 {len(result)} 张表"}


@router.post("/{ds_id}/uncollect-schema")
async def uncollect_schema(ds_id: int, request: dict | None = None):
    meta_svc = get_metadata_service()
    table_names = []
    if request is not None and "table_names" in request:
        table_names = request.get("table_names") or []
    result = await meta_svc.uncollect_schema(ds_id, table_names=table_names)
    return {"tables": result, "message": f"已取消采集 {len(result)} 张表"}


@router.get("/{ds_id}/remote-tables")
async def list_remote_tables(ds_id: int):
    meta_svc = get_metadata_service()
    tables = await meta_svc.list_remote_tables(ds_id)
    return {"tables": tables}


@router.get("/{ds_id}/schema/tables")
async def get_collected_table_summaries(ds_id: int):
    meta_svc = get_metadata_service()
    tables = await meta_svc.get_table_summaries(ds_id)
    return {"tables": tables}


@router.get("/{ds_id}/schema/stats")
async def get_collected_schema_stats(ds_id: int):
    meta_svc = get_metadata_service()
    return {"stats": await meta_svc.get_schema_stats(ds_id)}


@router.get("/{ds_id}/schema/tables/{table_id}")
async def get_collected_table_detail(ds_id: int, table_id: int):
    meta_svc = get_metadata_service()
    table = await meta_svc.get_table_detail(ds_id, table_id)
    if table is None:
        raise HTTPException(status_code=404, detail="表结构不存在")
    return {"table": table}


@router.get("/{ds_id}/schema")
async def get_collected_schema(ds_id: int):
    meta_svc = get_metadata_service()
    tables = await meta_svc.get_schema(ds_id)
    return {"tables": tables}
