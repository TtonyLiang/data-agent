"""企业空间服务。

企业空间当前只作为企业业务领域的逻辑容器；权限仍沿用现有用户-Agent授权，
不在本阶段引入完整多租户隔离。
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
