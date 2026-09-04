"""单公司部署的历史兼容容器服务。

本项目不提供多租户或多企业空间产品能力；该服务只为已有迁移数据和旧接口
保留默认容器读取，不应继续扩展为新的产品边界。
"""

from app.db.mysql import get_management_db
from app.models.knowledge import SemanticDomain
from app.models.workspace import EnterpriseWorkspace

DEFAULT_WORKSPACE_KEY = "default"
DEFAULT_WORKSPACE_NAME = "默认企业空间"


class WorkspaceService:
    async def list_workspaces(self) -> list[EnterpriseWorkspace]:
        rows = await get_management_db().execute_query(
            "SELECT * FROM enterprise_workspace ORDER BY id ASC"
        )
        return [EnterpriseWorkspace(**row) for row in rows]

    async def get_workspace(self, workspace_id: int) -> EnterpriseWorkspace | None:
        rows = await get_management_db().execute_query(
            "SELECT * FROM enterprise_workspace WHERE id = :id",
            {"id": workspace_id},
        )
        return EnterpriseWorkspace(**rows[0]) if rows else None

    async def get_default_workspace(self) -> EnterpriseWorkspace | None:
        rows = await get_management_db().execute_query(
            "SELECT * FROM enterprise_workspace WHERE workspace_key = :workspace_key LIMIT 1",
            {"workspace_key": DEFAULT_WORKSPACE_KEY},
        )
        return EnterpriseWorkspace(**rows[0]) if rows else None

    async def list_domains(self, workspace_id: int) -> list[SemanticDomain]:
        rows = await get_management_db().execute_query(
            "SELECT * FROM semantic_domain WHERE workspace_id = :workspace_id ORDER BY id ASC",
            {"workspace_id": workspace_id},
        )
        return [SemanticDomain(**row) for row in rows]


_service: WorkspaceService | None = None


def get_workspace_service() -> WorkspaceService:
    global _service
    if _service is None:
        _service = WorkspaceService()
    return _service
