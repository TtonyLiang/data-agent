"""MySQL 异步客户端 —— SQLAlchemy 异步引擎封装。

MySQLClient 是所有数据库操作的底层入口,提供:
1. ``execute_query``:执行 SELECT/INSERT/UPDATE/DELETE,返回 normalized rows。
2. ``execute_insert``:执行 INSERT 并返回 lastrowid。
3. ``execute_scalar``:执行查询返回第一个标量值。
4. ``execute_transaction``:在单个事务中执行多条语句。
5. ``execute_in_transaction``:提供事务性 session 给回调函数。

每个操作都记录:开始/结束日志、耗时、行数、SQL 预览(detailed_data_logging_enabled 时)。
连接超时和查询超时由系统配置控制(mysql_connect_timeout_seconds / mysql_query_timeout_seconds)。

全局连接池:
- ``get_business_db()``:默认业务数据库。
- ``get_management_db()``:管理数据库(配置、元数据、会话历史)。
- ``get_datasource_db(id)``:按 datasource_id 缓存的业务数据库连接。
  使用 asyncio.Lock 保证并发安全,连接配置变更后通过 ``invalidate_datasource_db`` 清缓存。
"""

import asyncio
import logging
import time as monotonic_time
from datetime import date, datetime, time
from decimal import Decimal
from urllib.parse import quote_plus

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.utils.logging_helpers import json_for_log, truncate_text

logger = logging.getLogger(__name__)


def normalize_query_value(value):
    """把数据库原生标量值转为 JSON 友好的 Python 值。

    - Decimal → int 或 float(避免 JSON 序列化报错)
    - datetime/date/time → ISO 字符串
    """
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    return value


def normalize_query_row(columns, row) -> dict:
    """把 SQLAlchemy 列名和行元组组合为 normalized dict。"""
    return {column: normalize_query_value(value) for column, value in zip(columns, row)}


class MySQLClient:
    """MySQL 异步客户端 —— 基于 SQLAlchemy async engine。"""

    def __init__(self, db_url: str):
        """创建异步引擎和 session 工厂。

        db_url 中的密码在日志中会被 redact_db_url 脱敏。
        """
        self._safe_url = redact_db_url(db_url)
        logger.info("mysql client init url=%s", self._safe_url)
        settings = get_settings()
        self._engine = create_async_engine(
            db_url,
            pool_size=5,
            max_overflow=10,
            echo=False,
            connect_args={"connect_timeout": settings.mysql_connect_timeout_seconds},
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def execute_query(self, sql: str, params: dict | None = None) -> list[dict]:
        """执行查询或语句,有行结果时返回 normalized rows。"""
        started_at = monotonic_time.monotonic()
        settings = get_settings()
        logger.info(
            "mysql query start url=%s sql_chars=%s params_keys=%s",
            self._safe_url,
            len(sql or ""),
            sorted((params or {}).keys()),
        )
        if settings.detailed_data_logging_enabled:
            logger.info(
                "mysql query preview url=%s sql=%s params=%s",
                self._safe_url,
                truncate_text(sql, 1600),
                json_for_log(params or {}),
            )
        async with self._session_factory() as session:
            await self._apply_query_timeout(session)
            result = await session.execute(text(sql), params or {})
            if result.returns_rows:
                columns = result.keys()
                rows = [normalize_query_row(columns, row) for row in result.fetchall()]
                logger.info(
                    "mysql query end url=%s duration_ms=%s rows=%s sample=%s",
                    self._safe_url,
                    round((monotonic_time.monotonic() - started_at) * 1000, 2),
                    len(rows),
                    json_for_log(rows[:3]) if settings.sql_sample_logging_enabled else "disabled",
                )
                return rows
            await session.commit()
            logger.info(
                "mysql query end url=%s duration_ms=%s rows=0 committed=true",
                self._safe_url,
                round((monotonic_time.monotonic() - started_at) * 1000, 2),
            )
            return []

    async def execute_insert(self, sql: str, params: dict | None = None) -> int:
        """执行 INSERT 语句并返回 lastrowid。"""
        started_at = monotonic_time.monotonic()
        settings = get_settings()
        logger.info(
            "mysql insert start url=%s sql_chars=%s params_keys=%s",
            self._safe_url,
            len(sql or ""),
            sorted((params or {}).keys()),
        )
        if settings.detailed_data_logging_enabled:
            logger.info(
                "mysql insert preview url=%s sql=%s params=%s",
                self._safe_url,
                truncate_text(sql, 1600),
                json_for_log(params or {}),
            )
        async with self._session_factory() as session:
            await self._apply_query_timeout(session)
            result = await session.execute(text(sql), params or {})
            await session.commit()
            lastrowid = int(result.lastrowid or 0)
            logger.info(
                "mysql insert end url=%s duration_ms=%s lastrowid=%s",
                self._safe_url,
                round((monotonic_time.monotonic() - started_at) * 1000, 2),
                lastrowid,
            )
            return lastrowid

    async def execute_scalar(self, sql: str, params: dict | None = None):
        """执行查询并返回第一个标量值。"""
        started_at = monotonic_time.monotonic()
        settings = get_settings()
        logger.info(
            "mysql scalar start url=%s sql_chars=%s params_keys=%s",
            self._safe_url,
            len(sql or ""),
            sorted((params or {}).keys()),
        )
        if settings.detailed_data_logging_enabled:
            logger.info(
                "mysql scalar preview url=%s sql=%s params=%s",
                self._safe_url,
                truncate_text(sql, 1600),
                json_for_log(params or {}),
            )
        async with self._session_factory() as session:
            await self._apply_query_timeout(session)
            result = await session.execute(text(sql), params or {})
            value = result.scalar()
            logger.info(
                "mysql scalar end url=%s duration_ms=%s value=%s",
                self._safe_url,
                round((monotonic_time.monotonic() - started_at) * 1000, 2),
                truncate_text(value, 500),
            )
            return value

    async def execute_transaction(self, statements: list[tuple[str, dict | None]]) -> None:
        """在单个事务中执行多条语句,任一失败则整体回滚。"""
        if not statements:
            return
        started_at = monotonic_time.monotonic()
        logger.info(
            "mysql transaction start url=%s statements=%s",
            self._safe_url,
            len(statements),
        )
        async with self._session_factory() as session:
            async with session.begin():
                await self._apply_query_timeout(session)
                for sql, params in statements:
                    await session.execute(text(sql), params or {})
        logger.info(
            "mysql transaction end url=%s duration_ms=%s statements=%s",
            self._safe_url,
            round((monotonic_time.monotonic() - started_at) * 1000, 2),
            len(statements),
        )

    async def execute_in_transaction(self, callback):
        """提供事务性 session 给回调函数,回调内可执行任意操作。"""
        started_at = monotonic_time.monotonic()
        logger.info("mysql transaction callback start url=%s", self._safe_url)
        async with self._session_factory() as session:
            async with session.begin():
                await self._apply_query_timeout(session)
                result = await callback(session)
        logger.info(
            "mysql transaction callback end url=%s duration_ms=%s",
            self._safe_url,
            round((monotonic_time.monotonic() - started_at) * 1000, 2),
        )
        return result

    async def _apply_query_timeout(self, session) -> None:
        """为 session 设置查询超时(MAX_EXECUTION_TIME),超时 0 表示不限制。"""
        timeout_ms = int(get_settings().mysql_query_timeout_seconds * 1000)
        if timeout_ms <= 0:
            return
        try:
            await session.execute(
                text("SET SESSION MAX_EXECUTION_TIME = :timeout_ms"),
                {"timeout_ms": timeout_ms},
            )
        except Exception as exc:
            logger.debug("mysql query timeout setting skipped url=%s error=%s", self._safe_url, exc)

    async def close(self):
        """关闭 SQLAlchemy 异步引擎(释放连接池)。"""
        logger.info("mysql client close url=%s", self._safe_url)
        await self._engine.dispose()


# ============================================================
# 全局连接池(进程级单例)
# ============================================================

_business_db: MySQLClient | None = None
_management_db: MySQLClient | None = None
# 按 datasource_id 缓存的业务数据库连接
_datasource_dbs: dict[int, MySQLClient] = {}
# 每个 datasource_id 一个锁,保证并发安全
_datasource_locks: dict[int, asyncio.Lock] = {}


def get_business_db() -> MySQLClient:
    """返回默认业务数据库客户端(从环境变量构建连接 URL)。"""
    global _business_db
    if _business_db is None:
        settings = get_settings()
        url = settings.business_db_url.replace("mysql+pymysql", "mysql+aiomysql")
        logger.info(
            "mysql business db create host=%s port=%s database=%s",
            settings.mysql_host,
            settings.mysql_port,
            settings.mysql_database,
        )
        _business_db = MySQLClient(url)
    return _business_db


def get_management_db() -> MySQLClient:
    """返回管理数据库客户端(配置、元数据、会话历史)。"""
    global _management_db
    if _management_db is None:
        settings = get_settings()
        url = settings.management_db_url.replace("mysql+pymysql", "mysql+aiomysql")
        logger.info(
            "mysql management db create host=%s port=%s database=%s",
            settings.management_mysql_host,
            settings.management_mysql_port,
            settings.management_mysql_database,
        )
        _management_db = MySQLClient(url)
    return _management_db


def build_mysql_async_url(
    username: str,
    password: str,
    host: str,
    port: int,
    database_name: str,
) -> str:
    """从连接参数构建 aiomysql SQLAlchemy URL。"""
    user = quote_plus(username)
    pwd = quote_plus(password)
    return f"mysql+aiomysql://{user}:{pwd}@{host}:{port}/{database_name}?charset=utf8mb4"


async def get_datasource_db(datasource_id: int) -> MySQLClient:
    """返回按 datasource_id 缓存的 MySQL 客户端。

    使用 asyncio.Lock 保证同一 datasource_id 的并发请求不会重复创建连接。
    连接配置变更后通过 ``invalidate_datasource_db`` 清缓存。
    """
    if datasource_id in _datasource_dbs:
        return _datasource_dbs[datasource_id]
    lock = _datasource_locks.setdefault(datasource_id, asyncio.Lock())
    async with lock:
        # 双重检查:锁内再检查一次,避免重复创建
        if datasource_id in _datasource_dbs:
            return _datasource_dbs[datasource_id]
        from app.services.datasource_service import get_datasource_service

        ds = await get_datasource_service().get(datasource_id)
        if ds is None:
            raise ValueError(f"数据源不存在: {datasource_id}")
        if ds.db_type.lower() != "mysql":
            raise ValueError(f"暂不支持的数据源类型: {ds.db_type}")
        logger.info(
            "mysql datasource db create datasource_id=%s db_type=%s host=%s "
            "port=%s database=%s username=%s",
            datasource_id,
            ds.db_type,
            ds.host,
            ds.port,
            ds.database_name,
            ds.username,
        )
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
    """关闭并移除缓存的数据源连接(配置变更后调用)。"""
    logger.info(
        "mysql datasource db invalidate datasource_id=%s cached=%s",
        datasource_id,
        datasource_id in _datasource_dbs,
    )
    client = _datasource_dbs.pop(datasource_id, None)
    if client is not None:
        await client.close()
    _datasource_locks.pop(datasource_id, None)


def redact_db_url(db_url: str) -> str:
    """把 SQLAlchemy URL 中的密码部分脱敏为 ***REDACTED***,用于日志输出。"""
    if "://" not in db_url or "@" not in db_url:
        return db_url
    scheme, rest = db_url.split("://", 1)
    credentials, host_part = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***REDACTED***@{host_part}"
