"""数据源管理服务 —— 业务库连接配置的增删改查与关联绑定。

DatasourceService 负责:
1. 数据源 CRUD,密码加密落盘(enc:v1: 前缀)。
2. 智能体与数据源的关联绑定(agent_datasource 关联表)。
3. 连接测试(SELECT 1 验证连通性)。

注意:
- ``delete`` 会级联删除该数据源关联的所有语义层资产(概念/指标/映射/规则/
  关系/模板)、语义领域、agent_datasource 绑定和采集元数据。
- ``update`` 后会自动 ``invalidate_datasource_db`` 清除缓存连接,下次查询时重建。
"""

import logging

from app.db.mysql import get_management_db, invalidate_datasource_db
from app.models.datasource import DatasourceConfig, DatasourceCreate, DatasourceUpdate
from app.services.secret_service import get_secret_service
from app.utils.logging_helpers import json_for_log

logger = logging.getLogger(__name__)


class DatasourceService:
    """数据源管理服务。"""

    async def create(self, ds: DatasourceCreate) -> int:
        """创建数据源,密码加密落盘,并绑定到指定智能体。"""
        logger.info(
            "datasource create input=%s",
            json_for_log(ds.model_dump(), text_limit=800),
        )
        db = get_management_db()
        encrypted_password = get_secret_service().encrypt(ds.password)
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
                "pwd": encrypted_password,
                "dbname": ds.database_name,
            },
        )
        # 创建后自动绑定到 agent
        if ds.agent_id:
            datasource_ids = await self.get_agent_datasource_ids(ds.agent_id)
            await self.set_agent_datasources(ds.agent_id, [*datasource_ids, ds_id])
        logger.info("datasource create result id=%s agent_id=%s", ds_id, ds.agent_id)
        return ds_id

    async def list_all(self) -> list[DatasourceConfig]:
        """返回所有数据源(管理页用)。"""
        logger.info("datasource list_all")
        db = get_management_db()
        rows = await db.execute_query("SELECT * FROM datasource ORDER BY id")
        logger.info("datasource list_all result count=%s", len(rows))
        return [self._from_row(row) for row in rows]

    async def list_by_agent(self, agent_id: int) -> list[DatasourceConfig]:
        """返回指定智能体绑定的数据源,优先查关联表,回退查旧 agent_id 字段。"""
        logger.info("datasource list_by_agent agent_id=%s", agent_id)
        db = get_management_db()
        # 优先查 agent_datasource 关联表(新链路)
        rows = await db.execute_query(
            "SELECT ds.* FROM datasource ds "
            "JOIN agent_datasource ad ON ad.datasource_id = ds.id "
            "WHERE ad.agent_id = :aid ORDER BY ds.id",
            {"aid": agent_id},
        )
        if not rows:
            # 回退:查旧的 datasource.agent_id 字段(兼容历史数据)
            rows = await db.execute_query(
                "SELECT * FROM datasource WHERE agent_id = :aid ORDER BY id",
                {"aid": agent_id},
            )
        result = [self._from_row(row) for row in rows]
        logger.info("datasource list_by_agent result agent_id=%s count=%s", agent_id, len(result))
        return result

    async def get(self, ds_id: int) -> DatasourceConfig | None:
        """按 id 加载单个数据源配置。"""
        logger.info("datasource get id=%s", ds_id)
        db = get_management_db()
        rows = await db.execute_query("SELECT * FROM datasource WHERE id = :id", {"id": ds_id})
        result = self._from_row(rows[0]) if rows else None
        logger.info("datasource get result id=%s found=%s", ds_id, bool(result))
        return result

    async def update(self, ds_id: int, ds: DatasourceUpdate) -> DatasourceConfig | None:
        """更新数据源字段,密码非空时才覆盖,更新后清缓存连接。"""
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
        # 密码非空时才覆盖(避免误清空)
        if ds.password:
            assignments.append("password = :pwd")
            params["pwd"] = get_secret_service().encrypt(ds.password)
        if ds.agent_id is not None:
            assignments.append("agent_id = :aid")
            params["aid"] = ds.agent_id
        await db.execute_query(
            f"UPDATE datasource SET {', '.join(assignments)} WHERE id = :id",
            params,
        )
        # 更新后清缓存,下次查询时重建连接
        await invalidate_datasource_db(ds_id)
        result = await self.get(ds_id)
        logger.info("datasource update result id=%s found=%s", ds_id, bool(result))
        return result

    async def delete(self, ds_id: int) -> bool:
        """删除数据源及其关联的全部语义层资产与采集元数据。

        级联删除顺序(先删子表再删主表,避免外键冲突):
        1. 语义资产(概念/关系/指标/规则/映射/模板)
        2. 语义领域(semantic_domain)
        3. 智能体绑定(agent_datasource)
        4. 采集元数据(meta_column → meta_table)
        5. 数据源本身(datasource)
        """
        logger.info("datasource delete id=%s", ds_id)
        db = get_management_db()
        statements = []
        # 第1步:删除语义资产(通过 semantic_domain 关联)
        for table in (
            "logic_form_template",
            "semantic_mapping",
            "semantic_rule",
            "semantic_metric",
            "semantic_relation",
            "semantic_concept",
        ):
            statements.append(
                (
                    f"DELETE FROM {table} WHERE domain_id IN "
                    "(SELECT id FROM semantic_domain WHERE datasource_id = :id)",
                    {"id": ds_id},
                )
            )
        # 第2-5步:删除语义领域、绑定、采集元数据、数据源本身
        statements.extend(
            [
                ("DELETE FROM semantic_domain WHERE datasource_id = :id", {"id": ds_id}),
                ("DELETE FROM agent_datasource WHERE datasource_id = :id", {"id": ds_id}),
                (
                    "DELETE FROM meta_column WHERE table_id IN "
                    "(SELECT id FROM meta_table WHERE datasource_id = :id)",
                    {"id": ds_id},
                ),
                ("DELETE FROM meta_table WHERE datasource_id = :id", {"id": ds_id}),
                ("DELETE FROM datasource WHERE id = :id", {"id": ds_id}),
            ]
        )
        if hasattr(db, "execute_transaction"):
            await db.execute_transaction(statements)
        else:
            for sql, params in statements:
                await db.execute_query(sql, params)
        await invalidate_datasource_db(ds_id)
        logger.info("datasource delete result id=%s ok=true", ds_id)
        return True

    async def belongs_to_agent(self, datasource_id: int, agent_id: int) -> bool:
        """检查指定智能体是否可访问该数据源(查关联表,回退查旧字段)。"""
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
        """返回指定智能体当前绑定的数据源 id 列表。"""
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
        """替换指定智能体的数据源绑定集合(先清空再插入)。"""
        logger.info(
            "datasource set_agent_datasources agent_id=%s datasource_ids=%s",
            agent_id,
            datasource_ids,
        )
        db = get_management_db()
        unique_ids = sorted({int(ds_id) for ds_id in datasource_ids})
        statements: list[tuple[str, dict | None]] = [
            ("DELETE FROM agent_datasource WHERE agent_id = :aid", {"aid": agent_id})
        ]
        for ds_id in unique_ids:
            statements.append(
                (
                    "INSERT INTO agent_datasource (agent_id, datasource_id) VALUES (:aid, :did)",
                    {"aid": agent_id, "did": ds_id},
                )
            )
        if hasattr(db, "execute_transaction"):
            await db.execute_transaction(statements)
        else:
            for sql, params in statements:
                await db.execute_query(sql, params)
        logger.info(
            "datasource set_agent_datasources result agent_id=%s datasource_ids=%s",
            agent_id,
            unique_ids,
        )
        return unique_ids

    def _from_row(self, row: dict) -> DatasourceConfig:
        """把数据库行转为 DatasourceConfig,密码字段解密。"""
        data = dict(row)
        data["password"] = get_secret_service().decrypt(data.get("password")) or ""
        return DatasourceConfig(**data)

    async def test_connection(self, ds_id: int) -> bool:
        """打开短连接执行 SELECT 1,验证数据源连通性。"""
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


# 全局单例
_datasource_service: DatasourceService | None = None


def get_datasource_service() -> DatasourceService:
    """返回进程级数据源服务单例。"""
    global _datasource_service
    if _datasource_service is None:
        _datasource_service = DatasourceService()
    return _datasource_service
