"""元数据管理服务 —— 业务库表结构的采集、查询与权限过滤。

MetadataService 负责:
1. ``list_remote_tables``:从业务库 information_schema 读取表清单(未采集的)。
2. ``collect_schema``:采集指定表的字段、外键信息,存入管理库(meta_table/meta_column)。
3. ``get_schema``:读取已采集的完整 schema(表 + 字段),供数据定位与 NL2SQL 使用。
4. ``get_authorized_schema``:在 ``get_schema`` 基础上叠加权限过滤,由
   ``PermissionService`` 根据 agent 的表/列权限规则移除或脱敏。

采集流程(``collect_schema``):
1. 从业务库 information_schema.TABLES 读取表清单,按 table_names 过滤。
2. 对每张表读取 information_schema.COLUMNS 采集字段信息。
3. 读取 KEY_COLUMN_USAGE 采集外键关系(用于推导 JOIN Hint)。
4. 通过事务 REPLACE 落库(meta_table + meta_column),已有记录先删再插。

注意:采集不会触及业务数据库的数据,只读取 schema 元信息。
"""

import logging

from sqlalchemy import text

from app.db.mysql import get_datasource_db, get_management_db
from app.models.datasource import ColumnMeta, TableMeta
from app.services.permission_service import get_permission_service
from app.utils.logging_helpers import json_for_log

logger = logging.getLogger(__name__)


class MetadataService:
    """元数据管理服务 —— 表/字段采集与查询。"""

    async def get_tables(self, datasource_id: int) -> list[TableMeta]:
        """返回指定数据源的已采集表元数据列表。"""
        logger.info("metadata get_tables datasource_id=%s", datasource_id)
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM meta_table WHERE datasource_id = :did ORDER BY id",
            {"did": datasource_id},
        )
        result = [TableMeta(**row) for row in rows]
        logger.info(
            "metadata get_tables result datasource_id=%s count=%s", datasource_id, len(result)
        )
        return result

    async def get_columns(self, table_id: int) -> list[ColumnMeta]:
        """返回指定表的已采集字段元数据列表。"""
        logger.info("metadata get_columns table_id=%s", table_id)
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM meta_column WHERE table_id = :tid ORDER BY id",
            {"tid": table_id},
        )
        result = [ColumnMeta(**row) for row in rows]
        logger.info("metadata get_columns result table_id=%s count=%s", table_id, len(result))
        return result

    async def list_remote_tables(self, datasource_id: int) -> list[dict]:
        """从业务库读取全部表清单,并标记哪些已采集、采集了多少字段。

        供前端"采集表选择"页面使用,返回按采集状态和 id 排序的列表。
        """
        logger.info("metadata list_remote_tables datasource_id=%s", datasource_id)
        biz_db = await get_datasource_db(datasource_id)
        mgmt_db = get_management_db()

        # 从业务库读取全部 BASE TABLE
        remote_rows = await biz_db.execute_query(
            "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME"
        )
        # 从管理库读取已采集表的 id 和字段数
        collected_rows = await mgmt_db.execute_query(
            "SELECT mt.id, mt.table_name, COUNT(mc.id) AS column_count "
            "FROM meta_table mt "
            "LEFT JOIN meta_column mc ON mc.table_id = mt.id "
            "WHERE mt.datasource_id = :did "
            "GROUP BY mt.id, mt.table_name",
            {"did": datasource_id},
        )
        collected = {
            row["table_name"]: {
                "table_id": row["id"],
                "column_count": int(row.get("column_count") or 0),
            }
            for row in collected_rows
        }
        catalog = [
            {
                "table_name": row["TABLE_NAME"],
                "table_comment": row.get("TABLE_COMMENT", ""),
                "collected": row["TABLE_NAME"] in collected,
                "table_id": collected.get(row["TABLE_NAME"], {}).get("table_id"),
                "column_count": collected.get(row["TABLE_NAME"], {}).get("column_count", 0),
            }
            for row in remote_rows
        ]
        result = sorted(
            catalog,
            key=lambda row: (
                row["table_id"] is None,  # 未采集的排后面
                int(row["table_id"] or 0),
                row["table_name"],
            ),
        )
        logger.info(
            "metadata list_remote_tables result datasource_id=%s count=%s sample=%s",
            datasource_id,
            len(result),
            json_for_log(result[:5]),
        )
        return result

    async def get_table_summaries(self, datasource_id: int) -> list[dict]:
        """返回已采集表列表(不含字段明细),供列表页展示。"""
        logger.info("metadata get_table_summaries datasource_id=%s", datasource_id)
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT mt.id, mt.datasource_id, mt.table_name, mt.table_comment, "
            "COUNT(mc.id) AS column_count "
            "FROM meta_table mt "
            "LEFT JOIN meta_column mc ON mc.table_id = mt.id "
            "WHERE mt.datasource_id = :did "
            "GROUP BY mt.id, mt.datasource_id, mt.table_name, mt.table_comment "
            "ORDER BY mt.id",
            {"did": datasource_id},
        )
        result = [
            {
                "id": row["id"],
                "datasource_id": row["datasource_id"],
                "table_name": row["table_name"],
                "table_comment": row.get("table_comment", ""),
                "column_count": int(row.get("column_count") or 0),
            }
            for row in rows
        ]
        logger.info(
            "metadata get_table_summaries result datasource_id=%s count=%s",
            datasource_id,
            len(result),
        )
        return result

    async def get_schema_stats(self, datasource_id: int) -> dict:
        """返回已采集表/字段数量及噪音等级评估。"""
        logger.info("metadata get_schema_stats datasource_id=%s", datasource_id)
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT COUNT(DISTINCT mt.id) AS table_count, COUNT(mc.id) AS column_count "
            "FROM meta_table mt "
            "LEFT JOIN meta_column mc ON mc.table_id = mt.id "
            "WHERE mt.datasource_id = :did",
            {"did": datasource_id},
        )
        row = rows[0] if rows else {}
        table_count = int(row.get("table_count") or 0)
        column_count = int(row.get("column_count") or 0)
        result = {
            "table_count": table_count,
            "column_count": column_count,
            # 超过 12 张表或 600 个字段视为高噪音,建议只采集核心事实表/维表
            "noise_level": "high" if table_count > 12 or column_count > 600 else "normal",
            "recommendation": (
                "建议只采集当前智能体会用到的核心事实表和维表，"
                "避免过多表结构干扰大模型。"
            )
            if table_count > 12 or column_count > 600
            else "采集规模正常。",
        }
        logger.info(
            "metadata get_schema_stats result datasource_id=%s stats=%s",
            datasource_id,
            json_for_log(result),
        )
        return result

    async def get_table_detail(self, datasource_id: int, table_id: int) -> dict | None:
        """返回单张表的完整信息(含字段列表)。"""
        logger.info(
            "metadata get_table_detail datasource_id=%s table_id=%s", datasource_id, table_id
        )
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM meta_table WHERE datasource_id = :did AND id = :tid",
            {"did": datasource_id, "tid": table_id},
        )
        if not rows:
            logger.info(
                "metadata get_table_detail result datasource_id=%s table_id=%s found=false",
                datasource_id,
                table_id,
            )
            return None
        table = TableMeta(**rows[0])
        table_data = table.model_dump()
        table_data["columns"] = [column.model_dump() for column in await self.get_columns(table.id)]
        logger.info(
            "metadata get_table_detail result datasource_id=%s table_id=%s column_count=%s",
            datasource_id,
            table_id,
            len(table_data["columns"]),
        )
        return table_data

    async def get_schema(self, datasource_id: int) -> list[dict]:
        """返回指定数据源的完整已采集 schema(表 + 字段),供数据定位与 NL2SQL 使用。"""
        logger.info("metadata get_schema datasource_id=%s", datasource_id)
        tables = await self.get_tables(datasource_id)
        schema = []
        for table in tables:
            columns = await self.get_columns(table.id)
            table_data = table.model_dump()
            table_data["columns"] = [column.model_dump() for column in columns]
            schema.append(table_data)
        logger.info(
            "metadata get_schema result datasource_id=%s table_count=%s column_count=%s",
            datasource_id,
            len(schema),
            sum(len(table.get("columns", [])) for table in schema),
        )
        return schema

    async def get_authorized_schema(
        self, datasource_id: int, agent_id: int | None = None
    ) -> list[dict]:
        """返回经权限过滤的 schema。

        与 get_schema 相比,多了 PermissionService 的表/列权限过滤:
        - 被拒的表整体移除
        - 被拒的列移除
        - 配置了脱敏策略的列标记 masking_policy
        """
        logger.info(
            "metadata get_authorized_schema datasource_id=%s agent_id=%s", datasource_id, agent_id
        )
        schema = await self.get_schema(datasource_id)
        result = await get_permission_service().filter_schema(agent_id, datasource_id, schema)
        logger.info(
            "metadata get_authorized_schema result datasource_id=%s agent_id=%s "
            "table_count=%s column_count=%s",
            datasource_id,
            agent_id,
            len(result),
            sum(len(table.get("columns", [])) for table in result),
        )
        return result

    async def collect_schema(
        self,
        datasource_id: int,
        table_names: list[str] | None = None,
    ) -> list[dict]:
        """从业务数据库采集指定表和字段元信息。

        采集流程:
        1. 从业务库 information_schema.TABLES 读取表清单
        2. 按 table_names 过滤(为空时采集全部表)
        3. 对每张表:读取 COLUMNS(字段) + KEY_COLUMN_USAGE(外键)
        4. 通过事务 REPLACE 落库(已有记录先删再插)

        table_names 显式传空列表时返回空结果(不采集)。
        """
        logger.info(
            "metadata collect_schema datasource_id=%s table_names=%s", datasource_id, table_names
        )
        biz_db = await get_datasource_db(datasource_id)
        mgmt_db = get_management_db()

        # 第1步:读取业务库全部 BASE TABLE
        tables = await biz_db.execute_query(
            "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME"
        )

        # 第2步:按 table_names 过滤(显式传空列表 = 不采集)
        selected_names = {name for name in (table_names or []) if name}
        if selected_names:
            tables = [row for row in tables if row["TABLE_NAME"] in selected_names]
        elif table_names is not None:
            logger.info(
                "metadata collect_schema result datasource_id=%s count=0 reason=empty_selection",
                datasource_id,
            )
            return []

        collected = []
        for t in tables:
            tname = t["TABLE_NAME"]
            tcomment = t.get("TABLE_COMMENT", "")

            # 第3a步:采集字段信息(字段名/类型/注释/主键)
            columns = await biz_db.execute_query(
                "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT, COLUMN_KEY "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :tn "
                "ORDER BY ORDINAL_POSITION",
                {"tn": tname},
            )

            # 第3b步:采集外键关系(用于推导 JOIN Hint)
            fk_rows = await biz_db.execute_query(
                "SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
                "FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :tn "
                "AND REFERENCED_TABLE_NAME IS NOT NULL",
                {"tn": tname},
            )
            fk_map: dict[str, str] = {}
            for fk in fk_rows:
                fk_map[fk["COLUMN_NAME"]] = (
                    f"{fk['REFERENCED_TABLE_NAME']}.{fk['REFERENCED_COLUMN_NAME']}"
                )

            # 第4步:通过事务 REPLACE 落库(先删旧记录再插新记录)
            table_id = await self._replace_collected_table(
                mgmt_db,
                datasource_id=datasource_id,
                table_name=tname,
                table_comment=tcomment,
                columns=columns,
                fk_map=fk_map,
            )

            collected.append(
                {
                    "table_name": tname,
                    "table_comment": tcomment,
                    "table_id": table_id,
                    "columns": len(columns),
                }
            )

        logger.info(
            "metadata collect_schema result datasource_id=%s collected=%s",
            datasource_id,
            json_for_log(collected),
        )
        return collected

    async def uncollect_schema(self, datasource_id: int, table_names: list[str]) -> list[dict]:
        """取消采集指定表,从管理库中删除对应的 meta_table 和 meta_column 记录。

        不触及业务数据库,只清除管理库中的元数据。
        """
        logger.info(
            "metadata uncollect_schema datasource_id=%s table_names=%s", datasource_id, table_names
        )
        selected_names = [name for name in table_names if name]
        if not selected_names:
            logger.info(
                "metadata uncollect_schema result datasource_id=%s count=0 reason=empty_selection",
                datasource_id,
            )
            return []

        db = get_management_db()
        removed = []
        for table_name in selected_names:
            rows = await db.execute_query(
                "SELECT id, table_name, table_comment FROM meta_table "
                "WHERE datasource_id = :did AND table_name = :tn",
                {"did": datasource_id, "tn": table_name},
            )
            if not rows:
                continue
            table_id = rows[0]["id"]
            # 先删字段再删表,事务保证原子性
            await db.execute_transaction(
                [
                    ("DELETE FROM meta_column WHERE table_id = :tid", {"tid": table_id}),
                    (
                        "DELETE FROM meta_table WHERE datasource_id = :did AND id = :tid",
                        {"did": datasource_id, "tid": table_id},
                    ),
                ]
            )
            removed.append(
                {
                    "table_name": rows[0]["table_name"],
                    "table_comment": rows[0].get("table_comment", ""),
                    "table_id": table_id,
                }
            )

        logger.info(
            "metadata uncollect_schema result datasource_id=%s removed=%s",
            datasource_id,
            json_for_log(removed),
        )
        return removed

    async def _replace_collected_table(
        self,
        mgmt_db,
        *,
        datasource_id: int,
        table_name: str,
        table_comment: str,
        columns: list[dict],
        fk_map: dict[str, str],
    ) -> int:
        """在单个事务中替换已采集表(先删字段再重建表记录再插字段)。

        使用 execute_in_transaction 获得一个 SQLAlchemy session,
        全部操作在同一事务内完成,保证原子性。
        """
        async def callback(session):
            # 1. 查找已有表记录
            existing = await session.execute(
                text("SELECT id FROM meta_table WHERE datasource_id = :did AND table_name = :tn"),
                {"did": datasource_id, "tn": table_name},
            )
            row = existing.mappings().first()
            if row:
                table_id = int(row["id"])
                # 已有记录:更新表注释
                await session.execute(
                    text(
                        "UPDATE meta_table SET table_comment = :tc "
                        "WHERE datasource_id = :did AND table_name = :tn"
                    ),
                    {"did": datasource_id, "tn": table_name, "tc": table_comment},
                )
            else:
                # 新表:插入记录
                inserted = await session.execute(
                    text(
                        "INSERT INTO meta_table (datasource_id, table_name, table_comment) "
                        "VALUES (:did, :tn, :tc)"
                    ),
                    {"did": datasource_id, "tn": table_name, "tc": table_comment},
                )
                table_id = int(inserted.lastrowid or 0)

            # 2. 先删除该表的所有旧字段(确保 REPLACE 语义)
            await session.execute(
                text("DELETE FROM meta_column WHERE table_id = :tid"),
                {"tid": table_id},
            )

            # 3. 插入新字段
            for col in columns:
                cname = col["COLUMN_NAME"]
                await session.execute(
                    text(
                        "INSERT INTO meta_column "
                        "(table_id, column_name, data_type, column_comment, is_primary_key, "
                        "is_foreign_key, foreign_key_ref) "
                        "VALUES (:tid, :cn, :ct, :cc, :pk, :fk, :fkr)"
                    ),
                    {
                        "tid": table_id,
                        "cn": cname,
                        "ct": col["DATA_TYPE"],
                        "cc": col.get("COLUMN_COMMENT", ""),
                        "pk": 1 if col.get("COLUMN_KEY") == "PRI" else 0,
                        "fk": 1 if cname in fk_map else 0,
                        "fkr": fk_map.get(cname),
                    },
                )
            return table_id

        return await mgmt_db.execute_in_transaction(callback)


# 全局单例
_metadata_service: MetadataService | None = None


def get_metadata_service() -> MetadataService:
    """返回进程级元数据服务单例。"""
    global _metadata_service
    if _metadata_service is None:
        _metadata_service = MetadataService()
    return _metadata_service
