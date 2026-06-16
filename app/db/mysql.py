from datetime import date, datetime, time
from decimal import Decimal
from urllib.parse import quote_plus

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings


def normalize_query_value(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    return value


def normalize_query_row(columns, row) -> dict:
    return {column: normalize_query_value(value) for column, value in zip(columns, row)}


class MySQLClient:
    """MySQL 异步客户端."""

    def __init__(self, db_url: str):
        self._engine = create_async_engine(db_url, pool_size=5, max_overflow=10, echo=False)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def execute_query(self, sql: str, params: dict | None = None) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(text(sql), params or {})
            if result.returns_rows:
                columns = result.keys()
                return [normalize_query_row(columns, row) for row in result.fetchall()]
            await session.commit()
            return []

    async def execute_insert(self, sql: str, params: dict | None = None) -> int:
        async with self._session_factory() as session:
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return int(result.lastrowid or 0)

    async def execute_scalar(self, sql: str, params: dict | None = None):
        async with self._session_factory() as session:
            result = await session.execute(text(sql), params or {})
            return result.scalar()

    async def close(self):
        await self._engine.dispose()


_business_db: MySQLClient | None = None
_management_db: MySQLClient | None = None
_datasource_dbs: dict[int, MySQLClient] = {}


def get_business_db() -> MySQLClient:
    global _business_db
    if _business_db is None:
        settings = get_settings()
        url = settings.business_db_url.replace("mysql+pymysql", "mysql+aiomysql")
        _business_db = MySQLClient(url)
    return _business_db


def get_management_db() -> MySQLClient:
    global _management_db
    if _management_db is None:
        settings = get_settings()
        url = settings.management_db_url.replace("mysql+pymysql", "mysql+aiomysql")
        _management_db = MySQLClient(url)
    return _management_db


def build_mysql_async_url(
    username: str,
    password: str,
    host: str,
    port: int,
    database_name: str,
) -> str:
    user = quote_plus(username)
    pwd = quote_plus(password)
    return f"mysql+aiomysql://{user}:{pwd}@{host}:{port}/{database_name}?charset=utf8mb4"


async def get_datasource_db(datasource_id: int) -> MySQLClient:
    if datasource_id not in _datasource_dbs:
        from app.services.datasource_service import get_datasource_service

        ds = await get_datasource_service().get(datasource_id)
        if ds is None:
            raise ValueError(f"数据源不存在: {datasource_id}")
        if ds.db_type.lower() != "mysql":
            raise ValueError(f"暂不支持的数据源类型: {ds.db_type}")
        _datasource_dbs[datasource_id] = MySQLClient(
            build_mysql_async_url(
                username=ds.username,
                password=ds.password,
                host=ds.host,
                port=ds.port,
                database_name=ds.database_name,
            )
        )
    return _datasource_dbs[datasource_id]


async def invalidate_datasource_db(datasource_id: int):
    client = _datasource_dbs.pop(datasource_id, None)
    if client is not None:
        await client.close()
