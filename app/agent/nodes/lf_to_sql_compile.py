from app.models.knowledge import LogicForm, SemanticRuntime
from app.services.semantic_runtime import get_semantic_runtime_service


async def lf_to_sql_compile_node(state: dict) -> dict:
    """把已校验的 LogicForm 编译为确定性 SELECT SQL。"""
    validation = state.get("lf_validation") or {}
    if not validation.get("valid"):
        return {"compiled_sql": "", "sql_text": ""}

    svc = get_semantic_runtime_service()
    logic_form = LogicForm(**state["logic_form"])
    runtime = SemanticRuntime(**state["semantic_runtime"])
    try:
        compiled = svc.compile_logic_form(logic_form, runtime)
    except Exception as exc:
        return {
            "compiled_sql": "",
            "sql_text": "",
            "sql_error": str(exc),
            "final_answer": f"SQL 编译失败: {exc}",
        }

    trace = {
        "used_assets": compiled.used_assets,
        "warnings": compiled.warnings,
        "compile_strategy": "deterministic_logic_form",
    }
    return {
        "compiled_query": compiled.model_dump(),
        "compiled_sql": compiled.sql,
        "sql_text": compiled.sql,
        "sql_error": None,
        "execution_trace": trace,
    }
