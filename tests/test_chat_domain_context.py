from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app import main
from app.agent.nodes import semantic_runtime_recall
from app.models.knowledge import SemanticDomain, SemanticRuntime
from app.models.user import PublicUser
from app.services.task_checkpoint_service import checkpoint_payload, reconcile_task_state

USER = PublicUser(id=9, username="domain-user", role="user", status="active")


class _CheckpointService:
    def __init__(self, checkpoint=None):
        self.checkpoint = checkpoint

    async def load(self, user_id, agent_id, session_id):
        assert (user_id, agent_id, session_id) == (9, 2, "session-domain")
        return self.checkpoint


@pytest.mark.asyncio
async def test_chat_business_context_prefers_explicit_domain_and_checks_permission(monkeypatch):
    domain_access = AsyncMock(return_value=7)
    monkeypatch.setattr(main, "require_domain_access", domain_access)
    monkeypatch.setattr(
        main,
        "get_task_checkpoint_service",
        lambda: _CheckpointService(
            {"domain_id": 3, "model_release_id": 30}
        ),
    )

    domain_id, release_id = await main.resolve_chat_business_context(
        {"domain_id": 8, "model_release_id": 80},
        USER,
        agent_id=2,
        session_id="session-domain",
    )

    assert (domain_id, release_id) == (8, 80)
    domain_access.assert_awaited_once_with(8, USER)


@pytest.mark.asyncio
async def test_chat_business_context_resumes_checkpoint_domain_with_same_permission_check(
    monkeypatch,
):
    domain_access = AsyncMock(return_value=7)
    monkeypatch.setattr(main, "require_domain_access", domain_access)
    monkeypatch.setattr(
        main,
        "get_task_checkpoint_service",
        lambda: _CheckpointService(
            {"domain_id": 3, "model_release_id": 30}
        ),
    )

    domain_id, release_id = await main.resolve_chat_business_context(
        {},
        USER,
        agent_id=2,
        session_id="session-domain",
    )

    assert (domain_id, release_id) == (3, 30)
    domain_access.assert_awaited_once_with(3, USER)


@pytest.mark.asyncio
async def test_chat_business_context_rejects_inaccessible_domain(monkeypatch):
    async def deny(_domain_id, _user):
        raise HTTPException(status_code=403, detail="无权访问该企业业务领域")

    monkeypatch.setattr(main, "require_domain_access", deny)
    monkeypatch.setattr(
        main,
        "get_task_checkpoint_service",
        lambda: _CheckpointService(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await main.resolve_chat_business_context(
            {"domain_id": 8},
            USER,
            agent_id=2,
            session_id="session-domain",
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_chat_request_passes_explicit_domain_to_persistent_graph_state(monkeypatch):
    seen = {}

    async def allow_agent(_agent_id, _user):
        return None

    async def allow_domain(domain_id, _user):
        assert domain_id == 8
        return 2

    async def prepare_state(**kwargs):
        seen.update(kwargs)
        return {
            "question": kwargs["question"],
            "agent_id": kwargs["agent_id"],
            "domain_id": kwargs["domain_id"],
            "model_release_id": kwargs["model_release_id"],
            "user_id": kwargs["user"].id,
            "session_id": kwargs["session_id"],
            "trace_id": kwargs["trace_id"],
        }

    class Graph:
        async def ainvoke(self, state, config=None):
            assert state["domain_id"] == 8
            assert state["model_release_id"] == 80
            return {**state, "final_answer": "ok", "sql_result": [], "execution_trace": {}}

    monkeypatch.setattr(main, "require_agent_access", allow_agent)
    monkeypatch.setattr(main, "require_domain_access", allow_domain)
    monkeypatch.setattr(main, "get_task_checkpoint_service", lambda: _CheckpointService())
    monkeypatch.setattr(main, "load_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        main,
        "resolve_chat_datasource_access",
        AsyncMock(return_value=5),
    )
    monkeypatch.setattr(main, "prepare_chat_state", prepare_state)
    monkeypatch.setattr(main, "get_graph", lambda: Graph())
    monkeypatch.setattr(main, "save_turn", AsyncMock())

    response = await main.chat(
        {
            "question": "查看贷款申请数量",
            "agent_id": 2,
            "domain_id": 8,
            "model_release_id": 80,
            "session_id": "session-domain",
        },
        current_user=USER,
    )

    assert seen["domain_id"] == 8
    assert seen["model_release_id"] == 80
    assert response["domain_id"] == 8
    assert response["model_release_id"] == 80


@pytest.mark.asyncio
async def test_chat_domain_datasource_does_not_require_agent_binding(monkeypatch):
    class RuntimeService:
        async def get_domain(self, domain_id):
            assert domain_id == 8
            return SimpleNamespace(id=8, datasource_id=5)

    datasource_access = AsyncMock(
        side_effect=AssertionError("domain-owned datasource must not use Agent binding")
    )
    monkeypatch.setattr(
        "app.services.semantic_runtime.get_semantic_runtime_service",
        lambda: RuntimeService(),
    )
    monkeypatch.setattr(main, "validate_datasource_access", datasource_access)

    resolved = await main.resolve_chat_datasource_access(
        2,
        None,
        "查看贷款申请数量",
        domain_id=8,
    )

    assert resolved == 5
    datasource_access.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_domain_rejects_foreign_datasource(monkeypatch):
    class RuntimeService:
        async def get_domain(self, _domain_id):
            return SimpleNamespace(id=8, datasource_id=5)

    monkeypatch.setattr(
        "app.services.semantic_runtime.get_semantic_runtime_service",
        lambda: RuntimeService(),
    )

    with pytest.raises(HTTPException, match="所选数据源与企业业务领域不一致"):
        await main.resolve_chat_datasource_access(
            2,
            6,
            "查看贷款申请数量",
            domain_id=8,
        )


def test_checkpoint_state_persists_explicit_domain_and_model_release():
    context = {
        "fingerprint": "domain-8-release-80",
        "domain_id": 8,
        "semantic_domain_id": 8,
        "model_release_id": 80,
    }
    state = reconcile_task_state(
        None,
        question="查看贷款申请数量",
        agent_id=2,
        user_id=9,
        session_id="session-domain",
        datasource_id=5,
        trace_id="trace-domain",
        domain_id=8,
        model_release_id=80,
        context=context,
    )

    assert state["domain_id"] == 8
    assert state["model_release_id"] == 80
    assert state["execution_trace"]["task"]["domain_id"] == 8
    assert checkpoint_payload(state)["model_release_id"] == 80


@pytest.mark.asyncio
async def test_semantic_recall_uses_explicit_domain_before_agent_default(monkeypatch):
    runtime = SemanticRuntime(
        domain=SemanticDomain(
            id=8,
            datasource_id=5,
            domain_key="loan",
            name="贷款业务",
            status="active",
        )
    )

    class RuntimeService:
        async def get_agent_bound_domain(self, _agent_id):
            raise AssertionError("explicit domain must not read the Agent default")

        async def get_domain(self, domain_id):
            assert domain_id == 8
            return runtime.domain

        async def build_runtime_from_snapshot(
            self,
            domain_id,
            snapshot_id,
            *,
            agent_id,
            expected_snapshot_hash,
        ):
            assert (domain_id, snapshot_id, agent_id) == (8, 18, 2)
            assert expected_snapshot_hash == "a" * 64
            return runtime

    class OntologyService:
        async def build_agent_context(self, domain_id, role):
            assert (domain_id, role) == (8, "user")
            return {
                "domain": {"id": 8, "name": "贷款业务"},
                "model_release": {"id": 80, "status": "active"},
                "semantic_snapshot": {"id": 18, "snapshot_hash": "a" * 64},
                "object_types": [],
                "link_types": [],
                "actions": [],
            }

    class EmbeddingService:
        async def embed_query(self, _question, agent_id=None):
            assert agent_id == 2
            return [0.1]

        async def get_index_identity(self, agent_id=None):
            assert agent_id == 2
            return {"config_id": 5, "version": "embedding-v1"}

    class VectorStore:
        def search(self, agent_id, _query_vector, **kwargs):
            assert agent_id == 2
            assert kwargs == {
                "domain_id": 8,
                "model_release_id": 80,
                "semantic_snapshot_id": 18,
                "embedding_model_config_id": 5,
                "embedding_model_version": "embedding-v1",
                "allow_legacy_fallback": False,
            }
            return []

    monkeypatch.setattr(
        semantic_runtime_recall,
        "get_semantic_runtime_service",
        lambda: RuntimeService(),
    )
    monkeypatch.setattr(
        semantic_runtime_recall,
        "get_ontology_service",
        lambda: OntologyService(),
    )
    monkeypatch.setattr(
        semantic_runtime_recall,
        "get_embedding_service",
        lambda: EmbeddingService(),
    )
    monkeypatch.setattr(
        semantic_runtime_recall,
        "get_vector_store",
        lambda: VectorStore(),
    )

    result = await semantic_runtime_recall.semantic_runtime_recall_node(
        {
            "agent_id": 2,
            "domain_id": 8,
            "model_release_id": 80,
            "datasource_id": 5,
            "user_role": "user",
            "question": "查看贷款申请数量",
        }
    )

    assert result["domain_id"] == 8
    assert result["model_release_id"] == 80
    assert result["semantic_runtime"]["domain"]["id"] == 8


@pytest.mark.asyncio
async def test_semantic_recall_rejects_model_release_mismatch(monkeypatch):
    domain = SemanticDomain(
        id=8,
        datasource_id=5,
        domain_key="loan",
        name="贷款业务",
        status="active",
    )

    class RuntimeService:
        async def get_domain(self, _domain_id):
            return domain

    class OntologyService:
        async def build_agent_context(self, _domain_id, role):
            assert role == "user"
            return {"model_release": {"id": 81, "status": "active"}}

    monkeypatch.setattr(
        semantic_runtime_recall,
        "get_semantic_runtime_service",
        lambda: RuntimeService(),
    )
    monkeypatch.setattr(
        semantic_runtime_recall,
        "get_ontology_service",
        lambda: OntologyService(),
    )

    result = await semantic_runtime_recall.semantic_runtime_recall_node(
        {
            "agent_id": 2,
            "domain_id": 8,
            "model_release_id": 80,
            "datasource_id": 5,
            "question": "查看贷款申请数量",
        }
    )

    assert result["semantic_runtime"] is None
    assert "不是当前业务领域的激活版本" in result["semantic_error"]
