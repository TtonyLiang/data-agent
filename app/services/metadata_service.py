from app.db.mysql import get_datasource_db, get_management_db
from app.models.datasource import ColumnMeta, TableMeta
from app.models.knowledge import SemanticModel


class MetadataService:
    """元数据管理服务：表/字段采集与查询."""

    async def get_tables(self, datasource_id: int) -> list[TableMeta]:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM meta_table WHERE datasource_id = :did",
            {"did": datasource_id},
        )
        return [TableMeta(**row) for row in rows]

    async def get_columns(self, table_id: int) -> list[ColumnMeta]:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM meta_column WHERE table_id = :tid",
            {"tid": table_id},
        )
        return [ColumnMeta(**row) for row in rows]

    async def get_semantic_models(self, agent_id: int) -> list[SemanticModel]:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM semantic_model WHERE agent_id = :aid",
            {"aid": agent_id},
        )
        return [SemanticModel(**row) for row in rows]

    async def collect_schema(self, datasource_id: int) -> list[dict]:
        """从业务数据库自动采集表和字段信息."""
        biz_db = await get_datasource_db(datasource_id)
        mgmt_db = get_management_db()

        # 获取所有表
        tables = await biz_db.execute_query(
            "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"
        )

        collected = []
        for t in tables:
            tname = t["TABLE_NAME"]
            tcomment = t.get("TABLE_COMMENT", "")

            # 插入或更新表记录
            existing = await mgmt_db.execute_query(
                "SELECT id FROM meta_table WHERE datasource_id = :did AND table_name = :tn",
                {"did": datasource_id, "tn": tname},
            )
            if existing:
                table_id = existing[0]["id"]
            else:
                await mgmt_db.execute_query(
                    "INSERT INTO meta_table (datasource_id, table_name, table_comment) "
                    "VALUES (:did, :tn, :tc)",
                    {"did": datasource_id, "tn": tname, "tc": tcomment},
                )
                row = await mgmt_db.execute_query(
                    "SELECT id FROM meta_table WHERE datasource_id = :did AND table_name = :tn",
                    {"did": datasource_id, "tn": tname},
                )
                table_id = row[0]["id"]

            # 获取字段
            columns = await biz_db.execute_query(
                "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT, COLUMN_KEY "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :tn",
                {"tn": tname},
            )

            # 获取外键信息
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

            for col in columns:
                cname = col["COLUMN_NAME"]
                ctype = col["DATA_TYPE"]
                ccomment = col.get("COLUMN_COMMENT", "")
                is_pk = 1 if col.get("COLUMN_KEY") == "PRI" else 0
                is_fk = 1 if cname in fk_map else 0
                fk_ref = fk_map.get(cname)

                existing_col = await mgmt_db.execute_query(
                    "SELECT id FROM meta_column WHERE table_id = :tid AND column_name = :cn",
                    {"tid": table_id, "cn": cname},
                )
                if not existing_col:
                    await mgmt_db.execute_query(
                        "INSERT INTO meta_column "
                        "(table_id, column_name, data_type, column_comment, is_primary_key, "
                        "is_foreign_key, foreign_key_ref) "
                        "VALUES (:tid, :cn, :ct, :cc, :pk, :fk, :fkr)",
                        {
                            "tid": table_id, "cn": cname, "ct": ctype,
                            "cc": ccomment, "pk": is_pk, "fk": is_fk, "fkr": fk_ref,
                        },
                    )

            collected.append({"table_name": tname, "columns": len(columns)})

        return collected


_metadata_service: MetadataService | None = None


def get_metadata_service() -> MetadataService:
    global _metadata_service
    if _metadata_service is None:
        _metadata_service = MetadataService()
    return _metadata_service
