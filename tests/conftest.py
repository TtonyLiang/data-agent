import pytest_asyncio

from app.db import mysql


@pytest_asyncio.fixture(autouse=True)
async def close_global_database_clients_after_test():
    """Keep process-level async engines from leaking across pytest event loops."""
    yield
    await mysql.close_database_clients()
