from app.db.mysql import get_management_db
from app.models.datasource import DatasourceConfig, DatasourceCreate


class DatasourceService:
    """数据源管理服务."""

    async def create(self, ds: DatasourceCreate) -> int:
        db = get_management_db()
        await db.execute_query(
            "INSERT INTO datasource "
            "(agent_id, name, db_type, host, port, username, password, database_name) "
            "VALUES (:aid, :name, :dtype, :host, :port, :user, :pwd, :dbname)",
            {
                "aid": ds.agent_id, "name": ds.name, "dtype": ds.db_type,
                "host": ds.host, "port": ds.port, "user": ds.username,
                "pwd": ds.password, "dbname": ds.database_name,
            },
        )
        row = await db.execute_query(
            "SELECT id FROM datasource WHERE agent_id = :aid ORDER BY id DESC LIMIT 1",
            {"aid": ds.agent_id},
        )
        return row[0]["id"]

    async def list_by_agent(self, agent_id: int) -> list[DatasourceConfig]:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM datasource WHERE agent_id = :aid", {"aid": agent_id}
        )
        return [DatasourceConfig(**row) for row in rows]

    async def get(self, ds_id: int) -> DatasourceConfig | None:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM datasource WHERE id = :id", {"id": ds_id}
        )
        return DatasourceConfig(**rows[0]) if rows else None

    async def test_connection(self, ds_id: int) -> bool:
        ds = await self.get(ds_id)
        if not ds:
            return False
        try:
            from app.db.mysql import MySQLClient, build_mysql_async_url

            url = build_mysql_async_url(
                username=ds.username,
                password=ds.password,
                host=ds.host,
                port=ds.port,
                database_name=ds.database_name,
            )
            client = MySQLClient(url)
            await client.execute_query("SELECT 1")
            await client.close()
            return True
        except Exception:
            return False


_datasource_service: DatasourceService | None = None


def get_datasource_service() -> DatasourceService:
    global _datasource_service
    if _datasource_service is None:
        _datasource_service = DatasourceService()
    return _datasource_service
