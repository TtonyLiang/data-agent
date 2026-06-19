import logging

from app.db.mysql import get_management_db, invalidate_datasource_db
from app.models.datasource import DatasourceConfig, DatasourceCreate, DatasourceUpdate
from app.utils.logging_helpers import json_for_log

logger = logging.getLogger(__name__)


class DatasourceService:
    """数据源管理服务."""

    async def create(self, ds: DatasourceCreate) -> int:
        """Create a datasource and optionally bind it to the owning agent."""
        logger.info(
            "datasource create input=%s",
            json_for_log(ds.model_dump(), text_limit=800),
        )
        db = get_management_db()
        ds_id = await db.execute_insert(
            "INSERT INTO datasource "
            "(agent_id, name, db_type, host, port, username, password, database_name) "
            "VALUES (:aid, :name, :dtype, :host, :port, :user, :pwd, :dbname)",
            {
                "aid": ds.agent_id,
                "name": ds.name,
                "dtype": ds.db_type,
                "host": ds.host,
                "port": ds.port,
                "user": ds.username,
                "pwd": ds.password,
                "dbname": ds.database_name,
            },
        )
        if ds.agent_id:
            datasource_ids = await self.get_agent_datasource_ids(ds.agent_id)
            await self.set_agent_datasources(ds.agent_id, [*datasource_ids, ds_id])
        logger.info("datasource create result id=%s agent_id=%s", ds_id, ds.agent_id)
        return ds_id

    async def list_all(self) -> list[DatasourceConfig]:
        """Return all datasource records for management screens."""
        logger.info("datasource list_all")
        db = get_management_db()
        rows = await db.execute_query("SELECT * FROM datasource ORDER BY id")
        logger.info("datasource list_all result count=%s", len(rows))
        return [DatasourceConfig(**row) for row in rows]

    async def list_by_agent(self, agent_id: int) -> list[DatasourceConfig]:
        """Return datasources explicitly bound to an agent, with legacy agent_id fallback."""
        logger.info("datasource list_by_agent agent_id=%s", agent_id)
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT ds.* FROM datasource ds "
            "JOIN agent_datasource ad ON ad.datasource_id = ds.id "
            "WHERE ad.agent_id = :aid ORDER BY ds.id",
            {"aid": agent_id},
        )
        if not rows:
            rows = await db.execute_query(
                "SELECT * FROM datasource WHERE agent_id = :aid ORDER BY id",
                {"aid": agent_id},
            )
        result = [DatasourceConfig(**row) for row in rows]
        logger.info("datasource list_by_agent result agent_id=%s count=%s", agent_id, len(result))
        return result

    async def get(self, ds_id: int) -> DatasourceConfig | None:
        """Load one datasource configuration by id."""
        logger.info("datasource get id=%s", ds_id)
        db = get_management_db()
        rows = await db.execute_query("SELECT * FROM datasource WHERE id = :id", {"id": ds_id})
        result = DatasourceConfig(**rows[0]) if rows else None
        logger.info("datasource get result id=%s found=%s", ds_id, bool(result))
        return result

    async def update(self, ds_id: int, ds: DatasourceUpdate) -> DatasourceConfig | None:
        """Update editable datasource fields and invalidate any cached connection."""
        logger.info(
            "datasource update id=%s input=%s", ds_id, json_for_log(ds.model_dump(), text_limit=800)
        )
        db = get_management_db()
        assignments = [
            "name = :name",
            "db_type = :dtype",
            "host = :host",
            "port = :port",
            "username = :user",
            "database_name = :dbname",
            "status = :status",
        ]
        params = {
            "id": ds_id,
            "name": ds.name,
            "dtype": ds.db_type,
            "host": ds.host,
            "port": ds.port,
            "user": ds.username,
            "dbname": ds.database_name,
            "status": ds.status,
        }
        if ds.password:
            assignments.append("password = :pwd")
            params["pwd"] = ds.password
        if ds.agent_id is not None:
            assignments.append("agent_id = :aid")
            params["aid"] = ds.agent_id
        await db.execute_query(
            f"UPDATE datasource SET {', '.join(assignments)} WHERE id = :id",
            params,
        )
        await invalidate_datasource_db(ds_id)
        result = await self.get(ds_id)
        logger.info("datasource update result id=%s found=%s", ds_id, bool(result))
        return result

    async def delete(self, ds_id: int) -> bool:
        """Delete a datasource and all collected/semantic metadata tied to it."""
        logger.info("datasource delete id=%s", ds_id)
        db = get_management_db()
        for table in (
            "logic_form_template",
            "semantic_mapping",
            "semantic_rule",
            "semantic_metric",
            "semantic_relation",
            "semantic_concept",
        ):
            await db.execute_query(
                f"DELETE FROM {table} WHERE domain_id IN "
                "(SELECT id FROM semantic_domain WHERE datasource_id = :id)",
                {"id": ds_id},
            )
        await db.execute_query(
            "DELETE FROM semantic_domain WHERE datasource_id = :id",
            {"id": ds_id},
        )
        await db.execute_query(
            "DELETE FROM agent_datasource WHERE datasource_id = :id",
            {"id": ds_id},
        )
        await db.execute_query(
            "DELETE FROM meta_column WHERE table_id IN "
            "(SELECT id FROM meta_table WHERE datasource_id = :id)",
            {"id": ds_id},
        )
        await db.execute_query(
            "DELETE FROM meta_table WHERE datasource_id = :id",
            {"id": ds_id},
        )
        await db.execute_query(
            "DELETE FROM datasource WHERE id = :id",
            {"id": ds_id},
        )
        await invalidate_datasource_db(ds_id)
        logger.info("datasource delete result id=%s ok=true", ds_id)
        return True

    async def belongs_to_agent(self, datasource_id: int, agent_id: int) -> bool:
        """Check whether an agent may use a datasource."""
        logger.info(
            "datasource belongs_to_agent datasource_id=%s agent_id=%s", datasource_id, agent_id
        )
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT datasource_id FROM agent_datasource "
            "WHERE datasource_id = :id AND agent_id = :aid",
            {"id": datasource_id, "aid": agent_id},
        )
        if rows:
            return True
        rows = await db.execute_query(
            "SELECT id FROM datasource WHERE id = :id AND agent_id = :aid",
            {"id": datasource_id, "aid": agent_id},
        )
        result = bool(rows)
        logger.info(
            "datasource belongs_to_agent result datasource_id=%s agent_id=%s ok=%s",
            datasource_id,
            agent_id,
            result,
        )
        return result

    async def get_agent_datasource_ids(self, agent_id: int) -> list[int]:
        """Return datasource ids currently bound to an agent."""
        logger.info("datasource get_agent_datasource_ids agent_id=%s", agent_id)
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT datasource_id FROM agent_datasource "
            "WHERE agent_id = :aid ORDER BY datasource_id",
            {"aid": agent_id},
        )
        result = [int(row["datasource_id"]) for row in rows]
        logger.info(
            "datasource get_agent_datasource_ids result agent_id=%s ids=%s", agent_id, result
        )
        return result

    async def set_agent_datasources(self, agent_id: int, datasource_ids: list[int]) -> list[int]:
        """Replace the datasource binding set for an agent."""
        logger.info(
            "datasource set_agent_datasources agent_id=%s datasource_ids=%s",
            agent_id,
            datasource_ids,
        )
        db = get_management_db()
        unique_ids = sorted({int(ds_id) for ds_id in datasource_ids})
        await db.execute_query(
            "DELETE FROM agent_datasource WHERE agent_id = :aid",
            {"aid": agent_id},
        )
        for ds_id in unique_ids:
            await db.execute_insert(
                "INSERT INTO agent_datasource (agent_id, datasource_id) VALUES (:aid, :did)",
                {"aid": agent_id, "did": ds_id},
            )
        logger.info(
            "datasource set_agent_datasources result agent_id=%s datasource_ids=%s",
            agent_id,
            unique_ids,
        )
        return unique_ids

    async def test_connection(self, ds_id: int) -> bool:
        """Open a short-lived datasource connection and run SELECT 1."""
        logger.info("datasource test_connection id=%s", ds_id)
        ds = await self.get(ds_id)
        if not ds:
            logger.info("datasource test_connection result id=%s ok=false reason=not_found", ds_id)
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
            logger.info("datasource test_connection result id=%s ok=true", ds_id)
            return True
        except Exception as exc:
            logger.exception(
                "datasource test_connection result id=%s ok=false error=%s", ds_id, exc
            )
            return False


_datasource_service: DatasourceService | None = None


def get_datasource_service() -> DatasourceService:
    """Return the process-wide datasource service singleton."""
    global _datasource_service
    if _datasource_service is None:
        _datasource_service = DatasourceService()
    return _datasource_service
