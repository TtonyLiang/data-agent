import pytest

from app.agent.ontology_tools import (
    ACTION_TOOL,
    QUERY_TOOL,
    build_ontology_tool_definitions,
    invoke_ontology_tool,
)


def test_ontology_tools_expose_only_bounded_contract():
    tools = build_ontology_tool_definitions()
    assert [item["name"] for item in tools] == [QUERY_TOOL, ACTION_TOOL]
    assert all(item["parameters"]["additionalProperties"] is False for item in tools)


@pytest.mark.asyncio
async def test_query_tool_forwards_only_supported_arguments():
    class FakeService:
        async def query_objects(self, domain_id, **kwargs):
            return {"domain_id": domain_id, **kwargs}

    result = await invoke_ontology_tool(
        FakeService(),
        7,
        QUERY_TOOL,
        {"object_type_key": "Material", "search": "MAT-001", "limit": 3},
        {"id": 2, "role": "user"},
    )
    assert result == {
        "domain_id": 7,
        "object_type_key": "Material",
        "search": "MAT-001",
        "limit": 3,
        "offset": 0,
    }

    with pytest.raises(ValueError, match="未知参数"):
        await invoke_ontology_tool(
            FakeService(), 7, QUERY_TOOL, {"sql": "SELECT 1"}, {"id": 2, "role": "user"}
        )


@pytest.mark.asyncio
async def test_action_tool_resolves_stable_key_and_builds_payload():
    class FakeService:
        async def get_action_type_by_key(self, domain_id, action_key):
            assert (domain_id, action_key) == (7, "reallocate_material")
            return {"id": 9}

        async def execute_action(self, domain_id, action_type_id, payload, user):
            return {
                "domain_id": domain_id,
                "action_type_id": action_type_id,
                "target_object_id": payload.target_object_id,
                "parameters": payload.parameters,
                "role": user["role"],
            }

    result = await invoke_ontology_tool(
        FakeService(),
        7,
        ACTION_TOOL,
        {
            "action_key": "reallocate_material",
            "target_object_id": 22,
            "parameters": {"new_status": "reallocated"},
        },
        {"id": 2, "role": "user"},
    )
    assert result == {
        "domain_id": 7,
        "action_type_id": 9,
        "target_object_id": 22,
        "parameters": {"new_status": "reallocated"},
        "role": "user",
    }

    with pytest.raises(ValueError, match="动作不存在"):
        class MissingActionService(FakeService):
            async def get_action_type_by_key(self, domain_id, action_key):
                return None

        await invoke_ontology_tool(
            MissingActionService(),
            7,
            ACTION_TOOL,
            {"action_key": "missing", "target_object_id": 22},
            {"id": 2, "role": "user"},
        )
