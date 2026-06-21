import asyncio
import json
from datetime import date, datetime, time
from decimal import Decimal

import pytest

from app.db import mysql
from app.db.mysql import normalize_query_value


def test_normalize_query_value_makes_common_mysql_types_json_safe():
    row = {
        "amount": normalize_query_value(Decimal("123.45")),
        "day": normalize_query_value(date(2026, 6, 13)),
        "created_at": normalize_query_value(datetime(2026, 6, 13, 8, 30, 5)),
        "clock": normalize_query_value(time(8, 30, 5)),
    }

    assert row == {
        "amount": 123.45,
        "day": "2026-06-13",
        "created_at": "2026-06-13T08:30:05",
        "clock": "08:30:05",
    }
    json.dumps(row)


@pytest.mark.asyncio
async def test_get_datasource_db_serializes_concurrent_initialization(monkeypatch):
    created = 0
    started = asyncio.Event()
    release = asyncio.Event()

    class FakeDatasourceService:
        async def get(self, datasource_id):
            started.set()
            await release.wait()
            return type(
                "Datasource",
                (),
                {
                    "db_type": "mysql",
                    "username": "u",
                    "password": "p",
                    "host": "h",
                    "port": 3306,
                    "database_name": "d",
                },
            )()

    class FakeClient:
        def __init__(self, _url):
            nonlocal created
            created += 1

    monkeypatch.setattr(
        "app.services.datasource_service.get_datasource_service",
        lambda: FakeDatasourceService(),
    )
    monkeypatch.setattr(mysql, "MySQLClient", FakeClient)
    mysql._datasource_dbs.clear()
    mysql._datasource_locks.clear()

    first = asyncio.create_task(mysql.get_datasource_db(7))
    await started.wait()
    second = asyncio.create_task(mysql.get_datasource_db(7))
    release.set()
    await asyncio.gather(first, second)

    assert created == 1
    mysql._datasource_dbs.clear()
    mysql._datasource_locks.clear()
