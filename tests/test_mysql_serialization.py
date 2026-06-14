import json
from datetime import date, datetime, time
from decimal import Decimal

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
