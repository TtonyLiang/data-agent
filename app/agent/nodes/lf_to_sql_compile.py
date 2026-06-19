import logging

from app.models.knowledge import LogicForm, SemanticRuntime
from app.services.semantic_runtime import get_semantic_runtime_service
from app.utils.logging_helpers import (
    json_for_log,
    log_node_end,
    log_node_error,
    log_node_start,
    truncate_text,
)

logger = logging.getLogger(__name__)


async def lf_to_sql_compile_node(state: dict) -> dict:
    """把已校验的 LogicForm 编译为确定性 SELECT SQL。"""
    log_node_start(
        logger,
        "lf_to_sql_compile",
        state,
        keys=("trace_id", "agent_id", "logic_form", "lf_validation"),
    )
    validation = state.get("lf_validation") or {}
    if not validation.get("valid"):
        result = {"compiled_sql": "", "sql_text": ""}
        log_node_end(logger, "lf_to_sql_compile", result)
        return result

    svc = get_semantic_runtime_service()
    logic_form = LogicForm(**state["logic_form"])
    runtime = SemanticRuntime(**state["semantic_runtime"])
    try:
        compiled = svc.compile_logic_form(logic_form, runtime)
    except Exception as exc:
        log_node_error(logger, "lf_to_sql_compile", exc, state)
        result = {
            "compiled_sql": "",
            "sql_text": "",
            "sql_error": str(exc),
            "final_answer": f"SQL 编译失败: {exc}",
        }
        log_node_end(logger, "lf_to_sql_compile", result)
        return result

    trace = {
        "used_assets": compiled.used_assets,
        "warnings": compiled.warnings,
        "compile_strategy": "deterministic_logic_form",
    }
    result = {
        "compiled_query": compiled.model_dump(),
        "compiled_sql": compiled.sql,
        "sql_text": compiled.sql,
        "sql_error": None,
        "execution_trace": trace,
    }
    logger.info(
        "lf compiled sql=%s used_assets=%s warnings=%s",
        truncate_text(compiled.sql, 1600),
        json_for_log(compiled.used_assets),
        json_for_log(compiled.warnings),
    )
    log_node_end(
        logger,
        "lf_to_sql_compile",
        {
            "compiled_sql": compiled.sql,
            "sql_error": None,
            "execution_trace": trace,
        },
    )
    return result
