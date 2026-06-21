import logging

from sqlalchemy import text

from app.db.mysql import get_datasource_db, get_management_db
from app.models.datasource import ColumnMeta, TableMeta
from app.services.permission_service import get_permission_service
from app.utils.logging_helpers import json_for_log

logger = logging.getLogger(__name__)


class MetadataService:
    """元数据管理服务：表/字段采集与查询."""

    async def get_tables(self, datasource_id: int) -> list[TableMeta]:
        """Return collected table metadata for a datasource."""
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
        """Return collected column metadata for one collected table."""
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
        """Return remote table names/comments without collecting columns."""
        logger.info("metadata list_remote_tables datasource_id=%s", datasource_id)
        biz_db = await get_datasource_db(datasource_id)
        mgmt_db = get_management_db()
        remote_rows = await biz_db.execute_query(
            "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME"
        )
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
                row["table_id"] is None,
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
        """Return collected table list without expanding all columns."""
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
        """Return table/column counts and a simple noise-level recommendation."""
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
        """Return one collected table with its expanded column list."""
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
        """Return collected tables with their columns for a datasource."""
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
        """Return collected schema after applying the agent's permission rules."""
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
        """从业务数据库采集指定表和字段信息；table_names 为空时保持兼容采集全部表."""
        logger.info(
            "metadata collect_schema datasource_id=%s table_names=%s", datasource_id, table_names
        )
        biz_db = await get_datasource_db(datasource_id)
        mgmt_db = get_management_db()

        tables = await biz_db.execute_query(
            "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME"
        )
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

            columns = await biz_db.execute_query(
                "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT, COLUMN_KEY "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :tn "
                "ORDER BY ORDINAL_POSITION",
                {"tn": tname},
            )

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
        """Remove collected metadata for selected tables without touching the business database."""
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
        async def callback(session):
            existing = await session.execute(
                text("SELECT id FROM meta_table WHERE datasource_id = :did AND table_name = :tn"),
                {"did": datasource_id, "tn": table_name},
            )
            row = existing.mappings().first()
            if row:
                table_id = int(row["id"])
                await session.execute(
                    text(
                        "UPDATE meta_table SET table_comment = :tc "
                        "WHERE datasource_id = :did AND table_name = :tn"
                    ),
                    {"did": datasource_id, "tn": table_name, "tc": table_comment},
                )
            else:
                inserted = await session.execute(
                    text(
                        "INSERT INTO meta_table (datasource_id, table_name, table_comment) "
                        "VALUES (:did, :tn, :tc)"
                    ),
                    {"did": datasource_id, "tn": table_name, "tc": table_comment},
                )
                table_id = int(inserted.lastrowid or 0)

            await session.execute(
                text("DELETE FROM meta_column WHERE table_id = :tid"),
                {"tid": table_id},
            )
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


_metadata_service: MetadataService | None = None


def get_metadata_service() -> MetadataService:
    """Return the process-wide metadata service singleton."""
    global _metadata_service
    if _metadata_service is None:
        _metadata_service = MetadataService()
    return _metadata_service
