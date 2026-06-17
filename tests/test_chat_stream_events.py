import asyncio
import json
import logging

import pytest

from app import main


class FakeStreamGraph:
    async def astream_events(self, state, version):
        assert version == "v2"
        assert state["question"] == "近三个月M1+逾期率是多少"
        yield {"event": "on_chain_start", "name": "sql_execute", "data": {}}
        yield {
            "event": "on_chain_end",
            "name": "sql_execute",
            "data": {
                "output": {
                    "intent": "data_query",
                    "logic_form": {"metrics": ["m1_plus_rate"], "dimensions": []},
                    "compiled_sql": "SELECT 1 AS m1_plus_rate",
                    "sql_result": [{"m1_plus_rate": 0.1234}],
                    "sql_error": None,
                    "final_answer": "近三个月M1+逾期率为12.34%。",
                }
            },
        }


class IncrementalStreamGraph:
    async def astream_events(self, state, version):
        yield {
            "event": "on_chain_end",
            "name": "intent_recognition",
            "data": {"output": {"intent": "data_query"}},
        }
        yield {
            "event": "on_chain_end",
            "name": "lf_to_sql_compile",
            "data": {"output": {"compiled_sql": "SELECT 1 AS value"}},
        }
        yield {
            "event": "on_chain_end",
            "name": "sql_execute",
            "data": {
                "output": {
                    "compiled_sql": "SELECT 1 AS value",
                    "sql_result": [{"value": 1}],
                    "sql_error": None,
                    "final_answer": "查询完成。",
                }
            },
        }


class FailingStreamGraph:
    async def astream_events(self, state, version):
        yield {"event": "on_chain_start", "name": "lf_to_sql_compile", "data": {}}
        raise RuntimeError("model connection dropped")


class SlowSemanticRuntimeGraph:
    async def astream_events(self, state, version):
        yield {"event": "on_chain_start", "name": "semantic_runtime_recall", "data": {}}
        await asyncio.sleep(0.03)
        yield {
            "event": "on_chain_end",
            "name": "semantic_runtime_recall",
            "data": {
                "output": {
                    "semantic_runtime": {"domain": {"name": "贷款风控"}},
                    "runtime_evidence": [],
                    "semantic_error": None,
                    "final_answer": "语义召回完成。",
                }
            },
        }


class TokenStreamGraph:
    async def astream_events(self, state, version):
        class Chunk:
            content = '{"metrics":["application_count"]}'
            additional_kwargs = {}

        yield {"event": "on_chain_start", "name": "nl2lf_generate", "data": {}}
        yield {"event": "on_chat_model_stream", "name": "ChatOpenAI", "data": {"chunk": Chunk()}}
        yield {
            "event": "on_chain_end",
            "name": "nl2lf_generate",
            "data": {
                "output": {
                    "logic_form": {"metrics": ["application_count"], "dimensions": []},
                    "final_answer": "完成。",
                }
            },
        }


@pytest.mark.asyncio
async def test_chat_stream_emits_final_answer_deltas_and_saves_only_final(monkeypatch):
    saved_turns = []

    async def fake_load_history(agent_id, session_id, limit=5):
        return []

    async def fake_save_turn(agent_id, session_id, question, answer, sql, sql_result, **kwargs):
        saved_turns.append(
            {
                "agent_id": agent_id,
                "session_id": session_id,
                "question": question,
                "answer": answer,
                "sql": sql,
                "logic_form": kwargs.get("logic_form"),
                "sql_result": sql_result,
                "reasoning_trace": kwargs.get("reasoning_trace"),
            }
        )

    async def fake_validate_datasource_access(agent_id, datasource_id):
        return None

    monkeypatch.setattr(main, "get_graph", lambda: FakeStreamGraph())
    monkeypatch.setattr(main, "load_history", fake_load_history)
    monkeypatch.setattr(main, "save_turn", fake_save_turn)
    monkeypatch.setattr(main, "validate_datasource_access", fake_validate_datasource_access)

    response = await main.chat_stream(
        {
            "question": "近三个月M1+逾期率是多少",
            "agent_id": 1,
            "datasource_id": 1,
            "session_id": "session-1",
        }
    )

    events = []
    async for item in response.body_iterator:
        events.append(item)

    event_names = [event["event"] for event in events]
    assert event_names == [
        "node_start",
        "node_complete",
        "answer_start",
        "answer_delta",
        "answer_complete",
        "result",
        "done",
    ]

    answer = "".join(
        json.loads(event["data"])["delta"]
        for event in events
        if event["event"] == "answer_delta"
    )
    assert answer == "近三个月M1+逾期率为12.34%。"

    result_event = next(event for event in events if event["event"] == "result")
    result = json.loads(result_event["data"])
    assert result["answer"] == answer
    assert result["sql"] == "SELECT 1 AS m1_plus_rate"

    assert saved_turns == [
        {
            "agent_id": 1,
            "session_id": "session-1",
            "question": "近三个月M1+逾期率是多少",
            "answer": "近三个月M1+逾期率为12.34%。",
            "sql": "SELECT 1 AS m1_plus_rate",
            "logic_form": {"metrics": ["m1_plus_rate"], "dimensions": []},
            "sql_result": [{"m1_plus_rate": 0.1234}],
            "reasoning_trace": [
                {
                    "node": "sql_execute",
                    "label": "SQL 执行",
                    "status": "done",
                    "reasoning": "",
                    "output": {
                        "row_count": 1,
                        "error": None,
                        "columns": ["m1_plus_rate"],
                        "sample_rows": [{"m1_plus_rate": 0.1234}],
                    },
                    "summary": "1 条结果",
                }
            ],
        }
    ]


@pytest.mark.asyncio
async def test_chat_stream_merges_incremental_node_outputs_before_result(monkeypatch):
    saved_turns = []

    async def fake_load_history(agent_id, session_id, limit=5):
        return []

    async def fake_save_turn(agent_id, session_id, question, answer, sql, sql_result, **kwargs):
        saved_turns.append({"answer": answer, "sql": sql, "sql_result": sql_result})

    async def fake_validate_datasource_access(agent_id, datasource_id):
        return None

    monkeypatch.setattr(main, "get_graph", lambda: IncrementalStreamGraph())
    monkeypatch.setattr(main, "load_history", fake_load_history)
    monkeypatch.setattr(main, "save_turn", fake_save_turn)
    monkeypatch.setattr(main, "validate_datasource_access", fake_validate_datasource_access)

    response = await main.chat_stream(
        {
            "question": "查一个值",
            "agent_id": 1,
            "datasource_id": 1,
            "session_id": "session-2",
        }
    )

    events = [item async for item in response.body_iterator]
    result = json.loads(next(event for event in events if event["event"] == "result")["data"])

    assert result["intent"] == "data_query"
    assert result["sql"] == "SELECT 1 AS value"
    assert saved_turns == [
        {
            "answer": "查询完成。",
            "sql": "SELECT 1 AS value",
            "sql_result": [{"value": 1}],
        }
    ]


@pytest.mark.asyncio
async def test_chat_stream_logs_sse_events(monkeypatch, caplog):
    async def fake_load_history(agent_id, session_id, limit=5):
        return []

    async def fake_save_turn(agent_id, session_id, question, answer, sql, sql_result, **kwargs):
        return None

    async def fake_validate_datasource_access(agent_id, datasource_id):
        return None

    monkeypatch.setattr(main, "get_graph", lambda: IncrementalStreamGraph())
    monkeypatch.setattr(main, "load_history", fake_load_history)
    monkeypatch.setattr(main, "save_turn", fake_save_turn)
    monkeypatch.setattr(main, "validate_datasource_access", fake_validate_datasource_access)

    response = await main.chat_stream(
        {
            "question": "查一个值",
            "agent_id": 1,
            "datasource_id": 1,
            "session_id": "session-3",
        }
    )

    with caplog.at_level(logging.INFO, logger="app.main"):
        _ = [item async for item in response.body_iterator]

    assert "SSE event=answer_delta" in caplog.text
    assert "SSE event=result" in caplog.text
    assert '"sql": "SELECT 1 AS value"' in caplog.text


@pytest.mark.asyncio
async def test_chat_stream_emits_progress_while_node_is_waiting(monkeypatch):
    async def fake_load_history(agent_id, session_id, limit=5):
        return []

    async def fake_save_turn(agent_id, session_id, question, answer, sql, sql_result, **kwargs):
        return None

    async def fake_validate_datasource_access(agent_id, datasource_id):
        return None

    monkeypatch.setattr(main, "get_graph", lambda: SlowSemanticRuntimeGraph())
    monkeypatch.setattr(main, "load_history", fake_load_history)
    monkeypatch.setattr(main, "save_turn", fake_save_turn)
    monkeypatch.setattr(main, "validate_datasource_access", fake_validate_datasource_access)
    monkeypatch.setattr(main, "STREAM_PROGRESS_INTERVAL_SECONDS", 0.01)

    response = await main.chat_stream(
        {
            "question": "申请笔数最多的前三种贷款是多少",
            "agent_id": 1,
            "datasource_id": 1,
            "session_id": "session-progress",
        }
    )

    events = [item async for item in response.body_iterator]
    event_names = [event["event"] for event in events]
    progress_event = next(event for event in events if event["event"] == "node_progress")
    progress_payload = json.loads(progress_event["data"])

    assert event_names.index("node_start") < event_names.index("node_progress")
    assert event_names.index("node_progress") < event_names.index("node_complete")
    assert progress_payload["node"] == "semantic_runtime_recall"
    assert "匹配语义资产" in progress_payload["message"]


@pytest.mark.asyncio
async def test_chat_stream_emits_model_tokens_inside_node(monkeypatch):
    async def fake_load_history(agent_id, session_id, limit=5):
        return []

    async def fake_save_turn(agent_id, session_id, question, answer, sql, sql_result, **kwargs):
        return None

    async def fake_validate_datasource_access(agent_id, datasource_id):
        return None

    monkeypatch.setattr(main, "get_graph", lambda: TokenStreamGraph())
    monkeypatch.setattr(main, "load_history", fake_load_history)
    monkeypatch.setattr(main, "save_turn", fake_save_turn)
    monkeypatch.setattr(main, "validate_datasource_access", fake_validate_datasource_access)

    response = await main.chat_stream(
        {
            "question": "申请笔数",
            "agent_id": 1,
            "datasource_id": 1,
            "session_id": "session-token",
        }
    )

    events = [item async for item in response.body_iterator]
    token_event = next(event for event in events if event["event"] == "token")
    token_payload = json.loads(token_event["data"])
    result = json.loads(next(event for event in events if event["event"] == "result")["data"])

    assert token_payload["node"] == "nl2lf_generate"
    assert token_payload["delta"] == '{"metrics":["application_count"]}'
    assert result["reasoning_trace"][0]["streamText"] == '{"metrics":["application_count"]}'


@pytest.mark.asyncio
async def test_chat_stream_returns_error_event_when_graph_fails(monkeypatch, caplog):
    async def fake_load_history(agent_id, session_id, limit=5):
        return []

    async def fake_save_turn(agent_id, session_id, question, answer, sql, sql_result, **kwargs):
        raise AssertionError("failed stream should not be saved as a complete turn")

    async def fake_validate_datasource_access(agent_id, datasource_id):
        return None

    monkeypatch.setattr(main, "get_graph", lambda: FailingStreamGraph())
    monkeypatch.setattr(main, "load_history", fake_load_history)
    monkeypatch.setattr(main, "save_turn", fake_save_turn)
    monkeypatch.setattr(main, "validate_datasource_access", fake_validate_datasource_access)

    response = await main.chat_stream(
        {
            "question": "查一个值",
            "agent_id": 1,
            "datasource_id": 1,
            "session_id": "session-4",
        }
    )

    with caplog.at_level(logging.ERROR, logger="app.main"):
        events = [item async for item in response.body_iterator]

    assert events[-1]["event"] == "error"
    error_payload = json.loads(events[-1]["data"])
    assert error_payload["message"] == "SQL 编译节点失败：大模型服务连接失败，请确认模型服务已启动，Base URL 可访问。（RuntimeError）"
    assert error_payload["label"] == "SQL 编译"
    assert error_payload["error_type"] == "RuntimeError"
    assert error_payload["detail"] == "model connection dropped"
    assert "chat stream failed" in caplog.text
