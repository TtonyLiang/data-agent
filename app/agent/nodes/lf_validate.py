"""LF 校验节点 —— 检查 LogicForm 引用的资产是否合法。

校验规则由 SemanticRuntimeService.validate_logic_form 执行。
校验失败 → 有修复机会时进入 lf_repair,否则进入 NL2SQL 兜底。
校验通过 → 进入 lf_to_sql_compile 编译 SQL。
"""

import logging

from app.agent.query_capability import validate_query_capability
from app.models.knowledge import LogicForm, SemanticRuntime
from app.services.semantic_runtime import get_semantic_runtime_service
from app.utils.logging_helpers import json_for_log, log_node_end, log_node_start

logger = logging.getLogger(__name__)


async def lf_validate_node(state: dict) -> dict:
    """校验 LogicForm 是否能被当前语义运行时执行。"""
    log_node_start(
        logger, "lf_validate", state, keys=("trace_id", "agent_id", "logic_form", "semantic_error")
    )
    logic_form_data = state.get("logic_form")
    runtime_data = state.get("semantic_runtime")
    if not logic_form_data or not runtime_data:
        result = {
            "lf_validation": {
                "valid": False,
                "errors": ["缺少 LogicForm 或知识库"],
                "warnings": [],
            },
            "final_answer": state.get("final_answer") or "未能构建可执行的语义查询。",
        }
        log_node_end(logger, "lf_validate", result)
        return result

    logic_form = LogicForm(**logic_form_data)
    runtime = SemanticRuntime(**runtime_data)
    capability_key = state.get("query_capability_key")
    capability_validation = None
    if capability_key and state.get("query_context"):
        capability_validation = validate_query_capability(
            str(capability_key), logic_form, state.get("query_context")
        )

    # Keep the existing deterministic semantic validation, but make the
    # capability boundary the first gate when the new context is active.
    svc = get_semantic_runtime_service()
    validation = svc.validate_logic_form(logic_form, runtime)
    result = {
        "lf_validation": validation.model_dump(),
        **(
            {"query_capability_validation": capability_validation}
            if capability_validation is not None
            else {}
        ),
    }
    if capability_validation is not None and not capability_validation.get("valid"):
        merged_errors = [
            *list(capability_validation.get("errors") or []),
            *list(validation.errors),
        ]
        result["lf_validation"] = validation.model_copy(
            update={
                "valid": False,
                "errors": list(dict.fromkeys(merged_errors)),
                "warnings": list(
                    dict.fromkeys(
                        [
                            *list(capability_validation.get("warnings") or []),
                            *list(validation.warnings),
                        ]
                    )
                ),
            }
        ).model_dump()
    if not result["lf_validation"].get("valid"):
        result["final_answer"] = "语义校验未通过: " + "；".join(
            result["lf_validation"].get("errors") or []
        )
    logger.info(
        "lf validation logic_form=%s validation=%s capability=%s",
        json_for_log(logic_form.model_dump()),
        json_for_log(result["lf_validation"]),
        json_for_log(result.get("query_capability_validation")),
    )
    log_node_end(logger, "lf_validate", result)
    return result
