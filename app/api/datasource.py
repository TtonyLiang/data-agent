from fastapi import APIRouter

from app.models.datasource import DatasourceCreate
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
    return {"datasources": [ds.model_dump() for ds in ds_list]}


@router.post("/{ds_id}/test")
async def test_connection(ds_id: int):
    svc = get_datasource_service()
    ok = await svc.test_connection(ds_id)
    return {"success": ok, "message": "连接成功" if ok else "连接失败"}


@router.post("/{ds_id}/collect-schema")
async def collect_schema(ds_id: int):
    meta_svc = get_metadata_service()
    result = await meta_svc.collect_schema(ds_id)
    return {"tables": result, "message": f"采集完成，共 {len(result)} 张表"}
