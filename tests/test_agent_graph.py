from app.agent.graph import route_after_sql_execute


def test_route_after_sql_execute_stops_when_result_exists_despite_stale_error():
    route = route_after_sql_execute(
        {
            "sql_result": [{"id": 1}],
            "sql_error": "previous failed attempt",
            "sql_retry_count": 0,
        }
    )

    assert route == "success"


def test_route_after_sql_execute_retries_when_error_without_result():
    route = route_after_sql_execute(
        {
            "sql_result": [],
            "sql_error": "table does not exist",
            "sql_retry_count": 0,
        }
    )

    assert route == "retry"
