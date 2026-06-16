from app.models.knowledge import LogicForm, SemanticRuntime
from app.services.semantic_runtime import get_semantic_runtime_service


async def lf_validate_node(state: dict) -> dict:
    """校验 LogicForm 是否能被当前语义运行时执行。"""
    logic_form_data = state.get("logic_form")
    runtime_data = state.get("semantic_runtime")
    if not logic_form_data or not runtime_data:
        return {
            "lf_validation": {"valid": False, "errors": ["缺少 LogicForm 或语义运行时"], "warnings": []},
            "final_answer": state.get("final_answer") or "未能构建可执行的语义查询。",
        }

    svc = get_semantic_runtime_service()
    logic_form = LogicForm(**logic_form_data)
    runtime = SemanticRuntime(**runtime_data)
    validation = svc.validate_logic_form(logic_form, runtime)
    result = {"lf_validation": validation.model_dump()}
    if not validation.valid:
        result["final_answer"] = "语义校验未通过: " + "；".join(validation.errors)
    return result
