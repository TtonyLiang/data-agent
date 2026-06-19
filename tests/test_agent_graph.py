from app.agent.graph import (
    route_after_nl2sql_fallback_compile,
    route_after_schema_recall,
    route_after_semantic_check,
    route_after_sql_compile,
    route_after_sql_execute,
)
from app.agent.nodes.intent import rule_based_intent, rule_based_intent_with_history


def test_rule_based_intent_treats_metric_business_question_as_data_query():
    assert rule_based_intent("高 PD 客户的余额和逾期情况") == "data_query"


def test_rule_based_intent_keeps_schema_question_as_metadata_query():
    assert rule_based_intent("订单表有哪些字段") == "metadata_query"


def test_followup_question_uses_recent_data_history():
    history = [
        {"role": "user", "content": "贷款排名前三的申请区域是什么，分别申请了多少笔"},
        {
            "role": "assistant",
            "content": "已返回前三个区域。",
            "logic_form": {"metrics": ["application_count"]},
        },
    ]

    assert rule_based_intent_with_history("前五呢", history) == "data_query"


def test_route_after_sql_compile_stops_when_sql_is_empty():
    assert route_after_sql_compile({"compiled_sql": "", "sql_error": "compile failed"}) == "failed"


def test_route_after_sql_compile_continues_when_sql_exists():
    assert route_after_sql_compile({"compiled_sql": "SELECT 1"}) == "compiled"


def test_route_after_semantic_check_can_pause_for_human_confirmation():
    assert (
        route_after_semantic_check(
            {"semantic_check": {"valid": True}, "require_sql_confirmation": True}
        )
        == "confirm"
    )
    assert (
        route_after_nl2sql_fallback_compile(
            {"compiled_sql": "SELECT 1", "require_sql_confirmation": True}
        )
        == "confirm"
    )


def test_route_after_semantic_check_repairs_invalid_check_before_blocking():
    assert (
        route_after_semantic_check({"semantic_check": {"valid": False}, "sql_retry_count": 0})
        == "repair"
    )
    assert (
        route_after_semantic_check({"semantic_check": {"valid": False}, "sql_retry_count": 2})
        == "invalid"
    )


def test_route_after_schema_recall_can_ask_for_clarification_when_enabled():
    assert (
        route_after_schema_recall(
            {
                "enable_low_confidence_clarification": True,
                "relevant_tables": [],
                "relevant_columns": [],
            }
        )
        == "clarify"
    )
    assert (
        route_after_schema_recall(
            {
                "enable_low_confidence_clarification": True,
                "relevant_tables": [{"table_name": "loan_application"}],
            }
        )
        == "continue"
    )
    assert (
        route_after_schema_recall(
            {
                "enable_low_confidence_clarification": False,
                "relevant_tables": [],
                "relevant_columns": [],
            }
        )
        == "continue"
    )


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
