from app.agent.nodes.intent import rule_based_intent
from app.agent.graph import route_after_sql_compile, route_after_sql_execute


def test_rule_based_intent_treats_metric_business_question_as_data_query():
    assert rule_based_intent("高 PD 客户的余额和逾期情况") == "data_query"


def test_rule_based_intent_keeps_schema_question_as_metadata_query():
    assert rule_based_intent("订单表有哪些字段") == "metadata_query"


def test_route_after_sql_compile_stops_when_sql_is_empty():
    assert route_after_sql_compile({"compiled_sql": "", "sql_error": "compile failed"}) == "failed"


def test_route_after_sql_compile_continues_when_sql_exists():
    assert route_after_sql_compile({"compiled_sql": "SELECT 1"}) == "compiled"


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
