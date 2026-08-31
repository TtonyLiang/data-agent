"""Small, explicit Ontology tool contract used by applications and agents.

The contract is intentionally narrower than a general tool registry.  A
domain-bound caller can search object instances and invoke a named, published
action.  Authorization, approval and optimistic-version checks remain in the
Ontology service and are never delegated to the model.
"""

from __future__ import annotations

from typing import Any

from app.models.ontology import OntologyActionExecutePayload
from app.services.ontology_service import OntologyService

QUERY_TOOL = "ontology_query_objects"
ACTION_TOOL = "ontology_execute_action"
ONTOLOGY_TOOL_NAMES = frozenset({QUERY_TOOL, ACTION_TOOL})


def build_ontology_tool_definitions() -> list[dict[str, Any]]:
    """Return OpenAI-compatible function definitions for a domain context."""
    return [
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
    ]


async def invoke_ontology_tool(
    service: OntologyService,
    domain_id: int,
    tool_name: str,
    arguments: dict[str, Any] | None,
    user: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch one bounded tool call after validating its argument shape."""
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
    raise ValueError(f"不支持的 Ontology 工具: {name}")
