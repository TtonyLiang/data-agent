"""Small, explicit Ontology tool contract used by applications and agents.

The module exposes three bounded runtime capabilities: object-instance search,
deterministic read-only Query Capability execution, and published Action
execution.  The Query Capability path validates the capability and LogicForm,
compiles deterministic SQL, and delegates SQL safety, SQL-level permission,
execution, and row masking to ``sql_execute_node``.  The API entry point also
requires a non-null datasource owned by the domain's agent.  Action
authorization, approval, and optimistic-version checks remain in the
Ontology service and are never delegated to the model.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.agent.nodes.sql_execute import sql_execute_node
from app.models.knowledge import LogicForm, SemanticRuntime
from app.models.ontology import OntologyActionExecutePayload
from app.services.ontology_service import OntologyService
from app.services.query_capability import QueryCapabilityFacade
from app.services.query_context import build_query_context
from app.services.semantic_runtime import get_semantic_runtime_service

QUERY_TOOL = "ontology_query_objects"
ACTION_TOOL = "ontology_execute_action"
QUERY_CAPABILITY_TOOL = "ontology_query_capability"
ONTOLOGY_TOOL_NAMES = frozenset({QUERY_TOOL, ACTION_TOOL, QUERY_CAPABILITY_TOOL})
_QUERY_CAPABILITY_EXECUTION_MODE = "deterministic_read_only_sql"
_QUERY_CAPABILITY_STATUS_VALIDATION_BLOCKED = "validation_blocked"
_QUERY_CAPABILITY_STATUS_SECURITY_BLOCKED = "security_blocked"
_QUERY_CAPABILITY_STATUS_PERMISSION_BLOCKED = "permission_blocked"
_QUERY_CAPABILITY_STATUS_DATABASE_ERROR = "database_error"
_QUERY_CAPABILITY_STATUS_SUCCEEDED = "succeeded"
_QUERY_CAPABILITY_ERROR_CATEGORY_DATASOURCE = "datasource"
_QUERY_CAPABILITY_SERVER_TRACE_FIELDS = frozenset(
    {
        "trace_id",
        "domain_id",
        "datasource_id",
        "ontology_release",
        "release",
        "query_capability_key",
        "target_object",
        "read_only",
        "used_assets",
        "warnings",
    }
)

_LOGIC_FORM_FIELDS = {
    "intent_type",
    "domain_key",
    "metrics",
    "dimensions",
    "filters",
    "time_range",
    "grain",
    "sort",
    "limit",
}
_QUERY_CAPABILITY_ARGUMENTS = {"capability_key", "logic_form", *_LOGIC_FORM_FIELDS}


def build_ontology_tool_definitions(
    *, include_query_capability: bool = False
) -> list[dict[str, Any]]:
    """Return OpenAI-compatible definitions for the bounded Ontology runtime.

    ``include_query_capability`` enables the independent read-only Query
    Capability definition in an application context.
    """
    definitions = [
        {
            "name": QUERY_TOOL,
            "description": "查询当前企业本体中的对象实例，只返回可访问的 active 对象。",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_type_key": {
                        "type": "string",
                        "description": "对象类型标识，例如 Material 或 Supplier。",
                    },
                    "search": {
                        "type": "string",
                        "description": "按对象显示名称或主标识模糊搜索。",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    "offset": {"type": "integer", "minimum": 0},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": ACTION_TOOL,
            "description": "执行当前企业本体中已发布且当前角色获授权的动作。",
            "parameters": {
                "type": "object",
                "required": ["action_key", "target_object_id"],
                "properties": {
                    "action_key": {"type": "string", "description": "动作标识。"},
                    "target_object_id": {"type": "integer", "minimum": 1},
                    "parameters": {"type": "object"},
                    "decision_context": {"type": "object"},
                    "approval_reference": {"type": ["string", "null"]},
                    "expected_version": {"type": ["integer", "null"], "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": QUERY_CAPABILITY_TOOL,
            "description": (
                "按已发布的只读 Query Capability 查询真实业务数据。"
                "工具先校验能力边界并确定性编译 SQL，再通过只读安全、权限和脱敏链路执行；"
                "不会调用写入 Action。"
            ),
            "parameters": {
                "type": "object",
                "required": ["capability_key"],
                "properties": {
                    "capability_key": {
                        "type": "string",
                        "description": "只读查询能力标识，从当前领域 query_capabilities 中选择。",
                    },
                    "logic_form": {
                        "type": "object",
                        "description": "可选的完整结构化业务查询；与下方查询参数合并。",
                        "additionalProperties": False,
                        "properties": {
                            "intent_type": {"type": "string"},
                            "domain_key": {"type": ["string", "null"]},
                            "metrics": {"type": "array", "items": {"type": "string"}},
                            "dimensions": {"type": "array", "items": {"type": "string"}},
                            "filters": {"type": "array", "items": {"type": "object"}},
                            "time_range": {"type": ["object", "null"]},
                            "grain": {"type": ["string", "null"]},
                            "sort": {"type": "array", "items": {"type": "object"}},
                            "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 1000},
                        },
                    },
                    "intent_type": {"type": "string"},
                    "domain_key": {"type": ["string", "null"]},
                    "metrics": {"type": "array", "items": {"type": "string"}},
                    "dimensions": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "array", "items": {"type": "object"}},
                    "time_range": {"type": ["object", "null"]},
                    "grain": {"type": ["string", "null"]},
                    "sort": {"type": "array", "items": {"type": "object"}},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 1000},
                },
                "additionalProperties": False,
            },
        },
    ]
    if not include_query_capability:
        return definitions[:2]
    return definitions


def build_query_capability_definitions(
    semantic_runtime: SemanticRuntime,
    ontology_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Expose formal Query Capability contracts for the read-only path."""
    return build_query_context("", semantic_runtime, ontology_context)["query_capabilities"]


async def _load_query_runtime_context(
    service: OntologyService,
    domain_id: int,
    user: dict[str, Any],
) -> tuple[dict[str, Any], SemanticRuntime]:
    """Load one bounded Ontology context and its semantic runtime.

    The loaded context/runtime pair is passed to the shared
    ``build_query_context`` builder by callers that need Query Capabilities.
    """
    context = await service.build_agent_context(domain_id, role=str(user.get("role") or "user"))
    runtime_service = get_semantic_runtime_service()
    domain = await runtime_service.get_domain(domain_id)
    if domain is None:
        raise ValueError("语义领域不存在")
    runtime = await runtime_service.build_runtime(
        agent_id=domain.agent_id,
        domain_id=domain_id,
    )
    return context, runtime


def _logic_form_from_arguments(arguments: dict[str, Any]) -> LogicForm:
    raw_payload = arguments.get("logic_form")
    if raw_payload is None:
        payload: dict[str, Any] = {}
    elif not isinstance(raw_payload, dict):
        raise ValueError("Query Capability LogicForm 必须是对象")
    else:
        payload = dict(raw_payload)
    unknown_logic_form = sorted(set(payload) - _LOGIC_FORM_FIELDS)
    if unknown_logic_form:
        raise ValueError(
            "Query Capability LogicForm 包含未知参数: "
            f"{', '.join(unknown_logic_form)}"
        )
    for field in _LOGIC_FORM_FIELDS:
        if field in arguments:
            payload[field] = arguments[field]
    return LogicForm.model_validate(payload)


def _new_query_trace_id() -> str:
    """Create a server-owned trace ID for one Query Capability invocation."""
    return f"trc_{uuid4().hex[:12]}"


def _query_execution_status(sql_error: Any) -> tuple[str, str]:
    """Classify the normalized SQL node outcome for the public result contract."""
    if sql_error is None:
        return _QUERY_CAPABILITY_STATUS_SUCCEEDED, "success"
    detail = str(sql_error)
    if "安全拦截" in detail:
        return _QUERY_CAPABILITY_STATUS_SECURITY_BLOCKED, "security"
    if "权限拦截" in detail:
        return _QUERY_CAPABILITY_STATUS_PERMISSION_BLOCKED, "permission"
    return _QUERY_CAPABILITY_STATUS_DATABASE_ERROR, "database"


def _actual_execution_sql(execution_result: dict[str, Any]) -> str | None:
    """Return the SQL normalized by ``sql_execute_node``, if it returned one."""
    actual_sql = execution_result.get("compiled_sql") or execution_result.get("sql_text")
    return str(actual_sql) if actual_sql else None


def _is_positive_datasource_id(value: Any) -> bool:
    """Return whether a datasource identifier is a strict positive integer."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


async def _invoke_query_capability(
    service: OntologyService,
    domain_id: int,
    arguments: dict[str, Any],
    user: dict[str, Any],
    *,
    ontology_context: dict[str, Any] | None = None,
    semantic_runtime: SemanticRuntime | None = None,
) -> dict[str, Any]:
    """Validate, compile, and execute one read-only Query Capability.

    The independent v1 path performs capability/LogicForm validation,
    deterministic compilation, and direct delegation to ``sql_execute_node``.
    It does not use the Chat graph's SQL-confirmation checkpoint and never
    calls ``execute_action()``.  The result distinguishes
    ``validation_blocked``, ``security_blocked``, ``permission_blocked``,
    ``database_error``, and ``succeeded``; only ``succeeded`` sets
    ``executed=True``.  It also returns the normalized ``executed_sql`` when
    available and server-owned trace/release metadata.
    """
    allowed = _QUERY_CAPABILITY_ARGUMENTS
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ValueError(f"Query Capability 工具包含未知参数: {', '.join(unknown)}")
    capability_key = str(arguments.get("capability_key") or "").strip()
    if not capability_key:
        raise ValueError("Query Capability 必须提供 capability_key")
    if ontology_context is None or semantic_runtime is None:
        ontology_context, semantic_runtime = await _load_query_runtime_context(
            service, domain_id, user
        )
    trace_id = _new_query_trace_id()
    datasource_id = semantic_runtime.domain.datasource_id
    ontology_release = ontology_context.get("release")
    capabilities = build_query_capability_definitions(semantic_runtime, ontology_context)
    facade = QueryCapabilityFacade()
    for item in capabilities:
        facade.register(item)
    capability = facade.resolve(capability_key)
    if capability is None:
        raise ValueError(f"未知 Query Capability: {capability_key}")
    logic_form = _logic_form_from_arguments(arguments)
    validation = facade.validate_capability(
        capability_key,
        logic_form,
        runtime=semantic_runtime,
        ontology_context=ontology_context,
    )
    capability_payload = capability.model_dump(mode="python")
    validation_payload = validation.model_dump(mode="python")
    capability_trace = {
        "trace_id": trace_id,
        "domain_id": domain_id,
        "datasource_id": datasource_id,
        "ontology_release": ontology_release,
        # Keep the context field name available for existing consumers.
        "release": ontology_release,
        "query_capability_key": capability.key,
        "target_object": capability.target_object,
        "read_only": True,
        "validation": validation_payload,
    }
    result: dict[str, Any] = {
        "tool": QUERY_CAPABILITY_TOOL,
        "read_only": True,
        "capability": capability_payload,
        "validation": validation_payload,
        "execution": {
            "executed": False,
            "attempted": False,
            "status": _QUERY_CAPABILITY_STATUS_VALIDATION_BLOCKED,
            "mode": _QUERY_CAPABILITY_STATUS_VALIDATION_BLOCKED,
            "message": "Query Capability 校验未通过，未执行查询。",
        },
        "sql_result": [],
        "sql_error": None,
        "final_answer": "",
        "execution_trace": capability_trace,
    }
    if not _is_positive_datasource_id(datasource_id):
        datasource_error = (
            "Query Capability datasource_id 必须是正整数，"
            f"当前值为 {datasource_id!r}，拒绝回退到默认 business DB。"
        )
        validation_payload = dict(validation_payload)
        validation_payload["valid"] = False
        validation_payload["errors"] = [
            *validation_payload.get("errors", []),
            datasource_error,
        ]
        capability_trace["validation"] = validation_payload
        result.update(
            {
                "validation": validation_payload,
                "execution": {
                    **result["execution"],
                    "message": "数据源校验未通过，未执行查询。",
                    "error_category": _QUERY_CAPABILITY_ERROR_CATEGORY_DATASOURCE,
                },
                "sql_error": datasource_error,
                "final_answer": f"查询未执行：{datasource_error}",
                "execution_trace": {
                    **capability_trace,
                    "query_capability_execution": {
                        "executed": False,
                        "attempted": False,
                        "status": _QUERY_CAPABILITY_STATUS_VALIDATION_BLOCKED,
                        "mode": _QUERY_CAPABILITY_STATUS_VALIDATION_BLOCKED,
                        "error_category": _QUERY_CAPABILITY_ERROR_CATEGORY_DATASOURCE,
                    },
                },
            }
        )
        return result
    if not validation.valid:
        errors = "；".join(validation.errors) or "未知校验错误"
        result.update(
            {
                "sql_error": f"Query Capability 校验未通过: {errors}",
                "final_answer": f"查询未执行：{errors}",
                "execution_trace": {
                    **capability_trace,
                    "query_capability_execution": {
                        "executed": False,
                        "attempted": False,
                        "status": _QUERY_CAPABILITY_STATUS_VALIDATION_BLOCKED,
                        "mode": _QUERY_CAPABILITY_STATUS_VALIDATION_BLOCKED,
                    },
                },
            }
        )
        return result

    compiled = facade.compile_logic_form(
        capability_key,
        logic_form,
        semantic_runtime,
        ontology_context=ontology_context,
        validation=validation,
    )
    compiled_plan = compiled.model_dump(mode="python")
    # ``sql`` is retained as the deterministic compiler output for backwards
    # compatibility; ``executed_sql`` is populated only from the SQL node's
    # normalized statement so callers cannot mistake the two.
    compiled_plan["executed_sql"] = None
    result["compiled_plan"] = compiled_plan

    # Keep this state deliberately small.  The existing SQL execution node is
    # the single owner of SQL safety normalization, permission checks,
    # datasource execution, and row masking.
    execution_state = {
        "trace_id": trace_id,
        "domain_id": domain_id,
        "agent_id": semantic_runtime.domain.agent_id,
        "datasource_id": datasource_id,
        "compiled_sql": compiled.sql,
        "sql_text": compiled.sql,
        "execution_trace": {
            **capability_trace,
            "used_assets": list(compiled.used_assets),
            "warnings": list(compiled.warnings),
            "compile_strategy": "deterministic_logic_form",
        },
    }
    try:
        execution_result = await sql_execute_node(execution_state)
    except Exception as exc:  # pragma: no cover - the node normally normalizes errors
        execution_result = {
            "sql_result": [],
            "sql_error": str(exc),
            "final_answer": f"SQL执行失败: {exc}",
            "execution_trace": dict(execution_state["execution_trace"]),
        }

    node_trace = execution_result.get("execution_trace") or {}
    if isinstance(node_trace, dict):
        node_trace = {
            key: value
            for key, value in node_trace.items()
            if key not in _QUERY_CAPABILITY_SERVER_TRACE_FIELDS
        }
    else:
        node_trace = {}
    sql_error = execution_result.get("sql_error")
    executed = sql_error is None
    status, error_category = _query_execution_status(sql_error)
    actual_sql = _actual_execution_sql(execution_result)
    compiled_plan["executed_sql"] = actual_sql
    merged_trace = {
        **execution_state["execution_trace"],
        **dict(node_trace),
        # These values are owned by this server-side invocation, not by tool
        # arguments or arbitrary node output.
        "trace_id": trace_id,
        "domain_id": domain_id,
        "datasource_id": datasource_id,
        "ontology_release": ontology_release,
        "release": ontology_release,
        "query_capability_key": capability.key,
        "target_object": capability.target_object,
        "read_only": True,
        "used_assets": list(compiled.used_assets),
        "warnings": list(compiled.warnings),
        "executed_sql": actual_sql,
        "query_capability_execution": {
            "executed": executed,
            "attempted": True,
            "status": status,
            "mode": _QUERY_CAPABILITY_EXECUTION_MODE,
            "error_category": error_category if not executed else None,
        },
    }
    if executed:
        message = "已通过现有只读 SQL 安全、权限和脱敏链路执行。"
        final_answer = execution_result.get("final_answer") or "查询已执行。"
    else:
        message = execution_result.get("final_answer") or str(sql_error)
        final_answer = message
    result.update(
        {
            "execution": {
                "executed": executed,
                "attempted": True,
                "status": status,
                "mode": _QUERY_CAPABILITY_EXECUTION_MODE,
                "message": message,
                "error_category": error_category if not executed else None,
            },
            "sql_result": execution_result.get("sql_result") or [],
            "sql_error": sql_error,
            "executed_sql": actual_sql,
            "final_answer": final_answer,
            "execution_trace": merged_trace,
        }
    )
    return result


async def invoke_ontology_tool(
    service: OntologyService,
    domain_id: int,
    tool_name: str,
    arguments: dict[str, Any] | None,
    user: dict[str, Any],
    *,
    ontology_context: dict[str, Any] | None = None,
    semantic_runtime: SemanticRuntime | None = None,
) -> dict[str, Any]:
    """Dispatch a bounded Ontology tool after validating its argument shape.

    Supported capabilities are object-instance query, read-only Query
    Capability execution, and published Action execution.  Query Capability
    remains read-only and is never routed through the Action executor.
    """
    name = str(tool_name or "").strip()
    args = dict(arguments or {})
    if name == QUERY_TOOL:
        allowed = {"object_type_key", "search", "limit", "offset"}
        unknown = sorted(set(args) - allowed)
        if unknown:
            raise ValueError(f"对象查询工具包含未知参数: {', '.join(unknown)}")
        return await service.query_objects(
            domain_id,
            object_type_key=args.get("object_type_key"),
            search=args.get("search"),
            limit=args.get("limit", 20),
            offset=args.get("offset", 0),
        )
    if name == ACTION_TOOL:
        allowed = {
            "action_key",
            "target_object_id",
            "parameters",
            "decision_context",
            "approval_reference",
            "expected_version",
        }
        unknown = sorted(set(args) - allowed)
        if unknown:
            raise ValueError(f"动作工具包含未知参数: {', '.join(unknown)}")
        action_key = str(args.get("action_key") or "").strip()
        action = await service.get_action_type_by_key(domain_id, action_key)
        if not action:
            raise ValueError(f"动作不存在: {action_key}")
        payload = OntologyActionExecutePayload.model_validate(
            {
                "target_object_id": args.get("target_object_id"),
                "parameters": args.get("parameters") or {},
                "decision_context": args.get("decision_context") or {},
                "approval_reference": args.get("approval_reference"),
                "expected_version": args.get("expected_version"),
            }
        )
        return await service.execute_action(domain_id, int(action["id"]), payload, user)
    if name == QUERY_CAPABILITY_TOOL:
        return await _invoke_query_capability(
            service,
            domain_id,
            args,
            user,
            ontology_context=ontology_context,
            semantic_runtime=semantic_runtime,
        )
    raise ValueError(f"不支持的 Ontology 工具: {name}")
