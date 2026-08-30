"""Persistent task checkpoints and deterministic turn reconciliation."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.mysql import get_management_db

logger = logging.getLogger(__name__)

TURN_MODES = frozenset({"new_task", "continue", "refine", "retry", "analyze", "respond"})

_RETRY_TERMS = (
    "重新执行",
    "再执行一次",
    "重新跑",
    "重跑",
    "重试",
    "再查一次",
    "确认执行",
)
_ANALYSIS_TERMS = ("分析", "趋势", "对比", "分布", "占比", "异常", "洞察", "报告", "图表")
_RESULT_REFERENCES = ("刚才", "上面", "前面", "这个结果", "查询结果", "这些结果", "该结果")
_RESPOND_TERMS = ("刚才查了什么", "用了什么sql", "用的什么sql", "结果多少行", "刚才的sql")
_CONTINUE_TERMS = ("继续", "继续执行", "接着执行", "恢复任务", "接着来")
_REFINE_TERMS = (
    "换成",
    "改成",
    "改为",
    "再按",
    "只看",
    "加上",
    "增加",
    "去掉",
    "不要",
    "上个月",
    "上周",
    "上季度",
    "去年",
    "前五",
    "前十",
    "呢",
)
_DIMENSION_REFINEMENT = re.compile(r"(?:再)?按.{1,20}(?:拆分|分组|统计|看|展示)")

_SEMANTIC_FIELDS = {
    "semantic_runtime",
    "runtime_evidence",
    "semantic_error",
}
_SCHEMA_FIELDS = {
    "relevant_tables",
    "relevant_columns",
    "likely_joins",
    "schema_scope",
    "schema_ready",
}
_QUERY_FIELDS = {
    "logic_form",
    "logic_form_attempted",
    "lf_validation",
    "compiled_query",
    "compiled_sql",
    "sql_text",
    "compile_attempted",
    "fallback_attempted",
    "nl2sql_fallback_error",
    "semantic_check",
    "semantic_check_attempted",
    "sql_result",
    "sql_result_present",
    "sql_executed",
    "sql_error",
    "sql_retry_count",
}
_ANALYSIS_FIELDS = {
    "plan",
    "python_code",
    "python_result",
    "report",
    "report_payload",
    "analysis_completed",
}
_TURN_OUTPUT_FIELDS = {
    "final_answer",
    "stream_chunks",
    "conversation",
    "conversation_metadata",
    "response",
    "clarification",
    "human_confirmation",
    "analysis_required",
    "react_iteration",
    "react_last_action",
    "react_next_action",
    "react_termination_reason",
    "react_history",
    "task_terminal",
}
_TRANSIENT_CHECKPOINT_FIELDS = {"chat_history", "stream_chunks"}


class CheckpointConflictError(RuntimeError):
    """Raised when a stale task state attempts to overwrite a newer checkpoint."""


def _is_concurrent_write_error(exc: DBAPIError) -> bool:
    """Recognize duplicate-key, lock-timeout and deadlock errors from MySQL drivers."""
    original = getattr(exc, "orig", exc)
    args = getattr(original, "args", ())
    try:
        error_code = int(args[0])
    except (IndexError, TypeError, ValueError):
        return False
    return error_code in {1062, 1205, 1213}


def classify_turn_mode(
    question: str,
    previous_state: dict[str, Any] | None,
    requested_mode: str | None = None,
) -> str:
    """Classify how a new user turn relates to the persisted task."""
    requested = str(requested_mode or "").strip().lower()
    if requested in TURN_MODES:
        return requested
    if not previous_state or not previous_state.get("task_id"):
        return "new_task"

    text = str(question or "").strip().lower()
    compact = text.replace(" ", "")
    prior_question = str(previous_state.get("question") or "").strip().lower().replace(" ", "")
    has_sql = bool(previous_state.get("compiled_sql") or previous_state.get("sql_text"))
    has_result = bool(previous_state.get("sql_executed")) or "sql_result" in previous_state

    if has_sql and any(term in compact for term in _RETRY_TERMS):
        return "retry"
    if has_result and any(term in compact for term in _ANALYSIS_TERMS) and any(
        term in compact for term in _RESULT_REFERENCES
    ):
        return "analyze"
    if any(term in compact for term in _RESPOND_TERMS):
        return "respond"
    if compact in _CONTINUE_TERMS:
        return "continue"
    if compact and compact == prior_question and previous_state.get("task_status") in {
        "running",
        "failed",
    }:
        return "continue"
    if any(term in compact for term in _REFINE_TERMS) or _DIMENSION_REFINEMENT.search(compact):
        return "refine"
    if previous_state.get("task_status") == "awaiting_input" and len(compact) <= 80:
        return "refine"
    return "new_task"


def reconcile_task_state(
    previous_state: dict[str, Any] | None,
    *,
    question: str,
    agent_id: int,
    user_id: int,
    session_id: str,
    datasource_id: int | None,
    trace_id: str,
    context: dict[str, Any],
    requested_mode: str | None = None,
    require_sql_confirmation: bool = False,
    enable_low_confidence_clarification: bool = False,
) -> dict[str, Any]:
    """Build the next runnable state while invalidating only dependent artifacts."""
    previous = deepcopy(previous_state or {})
    previous_subject = str(
        previous.get("enhanced_question")
        or previous.get("task_subject_question")
        or previous.get("question")
        or ""
    ).strip()
    mode = classify_turn_mode(question, previous, requested_mode)
    old_context = previous.get("task_context") or {}
    context_changed = bool(previous) and old_context.get("fingerprint") != context.get(
        "fingerprint"
    )

    if mode == "new_task":
        state: dict[str, Any] = {}
        task_id = f"task_{uuid.uuid4().hex}"
        task_revision = 1
    else:
        state = previous
        task_id = str(previous.get("task_id") or f"task_{uuid.uuid4().hex}")
        task_revision = int(previous.get("task_revision") or 0) + 1

    invalidated: set[str] = set()
    _remove_fields(state, _TURN_OUTPUT_FIELDS, invalidated)

    if mode == "new_task":
        _remove_fields(
            state,
            _SEMANTIC_FIELDS | _SCHEMA_FIELDS | _QUERY_FIELDS | _ANALYSIS_FIELDS,
            invalidated,
        )
        state.pop("enhanced_question", None)
        state.pop("semantic_enhancement", None)
        state.pop("intent", None)
    elif mode == "refine":
        state.pop("enhanced_question", None)
        state.pop("semantic_enhancement", None)
        invalidated.update({"enhanced_question", "semantic_enhancement"})
        fields = _QUERY_FIELDS | _ANALYSIS_FIELDS
        if _is_dimension_refinement(question):
            fields |= _SCHEMA_FIELDS
        _remove_fields(state, fields, invalidated)
        state["intent"] = "data_query"
    elif mode == "retry":
        _remove_fields(
            state,
            {
                "sql_result",
                "sql_result_present",
                "sql_executed",
                "sql_error",
                "sql_retry_count",
            }
            | _ANALYSIS_FIELDS,
            invalidated,
        )
        state["intent"] = "data_query"
    elif mode == "analyze":
        _remove_fields(state, _ANALYSIS_FIELDS, invalidated)
        state["intent"] = "data_query"
        state["force_analysis"] = True
    elif mode == "respond":
        state["intent"] = "data_query"

    if context_changed:
        _remove_fields(
            state,
            _SEMANTIC_FIELDS | _SCHEMA_FIELDS | _QUERY_FIELDS | _ANALYSIS_FIELDS,
            invalidated,
        )
        state.pop("enhanced_question", None)
        state.pop("semantic_enhancement", None)
        state.pop("intent", None)

    working_question = question
    if mode in {"continue", "retry"} and previous.get("question"):
        working_question = str(previous["question"])

    prior_trace = previous.get("execution_trace") or {}
    reused = _reused_artifacts(state)
    state.update(
        {
            "question": working_question,
            "user_turn_question": question,
            "agent_id": agent_id,
            "user_id": user_id,
            "session_id": session_id,
            "datasource_id": datasource_id,
            "trace_id": trace_id,
            "task_id": task_id,
            "task_subject_question": previous_subject if mode != "new_task" else question,
            "turn_id": f"turn_{uuid.uuid4().hex}",
            "task_revision": task_revision,
            "turn_mode": mode,
            "task_status": "running",
            "task_terminal": False,
            "task_context": context,
            "context_invalidated": context_changed,
            "invalidated_artifacts": sorted(invalidated),
            "reused_artifacts": reused,
            "require_sql_confirmation": require_sql_confirmation,
            "enable_low_confidence_clarification": enable_low_confidence_clarification,
            "react_iteration": 0,
            "react_history": [],
            "react_last_action": "",
            "react_next_action": "",
            "react_termination_reason": None,
            "analysis_required": mode == "analyze",
            "execution_trace": {
                "trace_id": trace_id,
                "task": {
                    "task_id": task_id,
                    "turn_mode": mode,
                    "resumed": mode != "new_task",
                    "context_invalidated": context_changed,
                    "reused_artifacts": reused,
                    "invalidated_artifacts": sorted(invalidated),
                    "prior_trace_id": prior_trace.get("trace_id"),
                },
                **(
                    {"compile_strategy": prior_trace.get("compile_strategy")}
                    if prior_trace.get("compile_strategy")
                    else {}
                ),
            },
        }
    )
    if mode != "analyze":
        state.pop("force_analysis", None)
    return state


def checkpoint_payload(state: dict[str, Any]) -> dict[str, Any]:
    """Return the durable, JSON-compatible part of an agent state."""
    payload = {
        key: value
        for key, value in state.items()
        if key not in _TRANSIENT_CHECKPOINT_FIELDS and not key.startswith("_")
    }
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def _remove_fields(state: dict[str, Any], fields: set[str], invalidated: set[str]) -> None:
    for field in fields:
        if field in state:
            state.pop(field, None)
            invalidated.add(field)


def _is_dimension_refinement(question: str) -> bool:
    compact = str(question or "").lower().replace(" ", "")
    return bool(_DIMENSION_REFINEMENT.search(compact)) or any(
        term in compact for term in ("增加维度", "加个维度", "按地区", "按区域", "按产品")
    )


def _reused_artifacts(state: dict[str, Any]) -> list[str]:
    groups = (
        ("semantic_runtime", bool(state.get("semantic_runtime"))),
        ("schema", bool(state.get("schema_ready") or state.get("relevant_tables"))),
        ("logic_form", bool(state.get("logic_form"))),
        ("compiled_sql", bool(state.get("compiled_sql") or state.get("sql_text"))),
        ("sql_result", bool(state.get("sql_executed")) or "sql_result" in state),
        ("analysis", bool(state.get("python_result") or state.get("report_payload"))),
    )
    return [name for name, present in groups if present]


class TaskCheckpointService:
    """MySQL-backed checkpoint storage keyed by user, agent and session."""

    async def load(self, user_id: int, agent_id: int, session_id: str) -> dict[str, Any] | None:
        rows = await get_management_db().execute_query(
            "SELECT revision, checkpoint_json, status, task_id, turn_id, turn_mode "
            "FROM agent_task_checkpoint "
            "WHERE user_id = :user_id AND agent_id = :agent_id AND session_id = :session_id",
            {"user_id": user_id, "agent_id": agent_id, "session_id": session_id},
        )
        if not rows:
            return None
        row = rows[0]
        payload = row.get("checkpoint_json") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                logger.warning(
                    "invalid checkpoint json agent_id=%s session_id=%s",
                    agent_id,
                    session_id,
                )
                return None
        if not isinstance(payload, dict):
            return None
        payload["checkpoint_revision"] = int(row.get("revision") or 0)
        payload["task_status"] = row.get("status") or payload.get("task_status")
        payload["task_id"] = row.get("task_id") or payload.get("task_id")
        payload["turn_id"] = row.get("turn_id") or payload.get("turn_id")
        payload["turn_mode"] = row.get("turn_mode") or payload.get("turn_mode")
        return payload

    async def save(self, state: dict[str, Any]) -> int:
        payload = checkpoint_payload(state)
        raw_revision = state.get("checkpoint_revision")
        expected_revision = (
            None if raw_revision in {None, ""} else int(raw_revision)
        )
        if expected_revision is not None and expected_revision < 1:
            raise ValueError("checkpoint_revision must be a positive integer")

        key_params = {
            "user_id": int(state.get("user_id") or 0),
            "agent_id": int(state.get("agent_id") or 0),
            "session_id": str(state.get("session_id") or ""),
        }
        write_params = {
            **key_params,
            "task_id": str(state.get("task_id") or ""),
            "turn_id": str(state.get("turn_id") or ""),
            "turn_mode": str(state.get("turn_mode") or "new_task"),
            "status": str(state.get("task_status") or "running"),
            "current_action": str(state.get("react_last_action") or ""),
        }
        db = get_management_db()

        def params_for_revision(revision: int) -> dict[str, Any]:
            versioned_payload = {**payload, "checkpoint_revision": revision}
            return {
                **write_params,
                "expected_revision": revision - 1,
                "new_revision": revision,
                "checkpoint_json": json.dumps(versioned_payload, ensure_ascii=False),
            }

        async def save_in_transaction(session) -> int:
            locked = await session.execute(
                text(
                    "SELECT revision FROM agent_task_checkpoint "
                    "WHERE user_id = :user_id AND agent_id = :agent_id "
                    "AND session_id = :session_id FOR UPDATE"
                ),
                key_params,
            )
            row = locked.mappings().first()

            if row is None:
                if expected_revision is not None:
                    raise CheckpointConflictError(
                        "checkpoint was deleted or replaced before this state could be saved"
                    )
                params = params_for_revision(1)
                await session.execute(
                    text(
                        "INSERT INTO agent_task_checkpoint "
                        "(user_id, agent_id, session_id, task_id, turn_id, revision, status, "
                        "turn_mode, current_action, checkpoint_json) "
                        "VALUES (:user_id, :agent_id, :session_id, :task_id, :turn_id, "
                        ":new_revision, :status, :turn_mode, :current_action, :checkpoint_json)"
                    ),
                    params,
                )
                return 1

            current_revision = int(row["revision"])
            if expected_revision != current_revision:
                raise CheckpointConflictError(
                    "stale checkpoint revision: "
                    f"expected {expected_revision}, current {current_revision}"
                )

            new_revision = current_revision + 1
            params = params_for_revision(new_revision)
            updated = await session.execute(
                text(
                    "UPDATE agent_task_checkpoint SET task_id = :task_id, turn_id = :turn_id, "
                    "revision = :new_revision, status = :status, turn_mode = :turn_mode, "
                    "current_action = :current_action, checkpoint_json = :checkpoint_json "
                    "WHERE user_id = :user_id AND agent_id = :agent_id "
                    "AND session_id = :session_id AND revision = :expected_revision"
                ),
                params,
            )
            if updated.rowcount != 1:
                raise CheckpointConflictError(
                    "checkpoint changed while the current state was being saved"
                )
            return new_revision

        try:
            return await db.execute_in_transaction(save_in_transaction)
        except DBAPIError as exc:
            if _is_concurrent_write_error(exc):
                raise CheckpointConflictError(
                    "checkpoint write conflicted with another active turn"
                ) from exc
            raise

    async def delete(self, user_id: int | None, agent_id: int, session_id: str) -> None:
        if user_id is None:
            sql = (
                "DELETE FROM agent_task_checkpoint "
                "WHERE agent_id = :agent_id AND session_id = :session_id"
            )
            params = {"agent_id": agent_id, "session_id": session_id}
        else:
            sql = (
                "DELETE FROM agent_task_checkpoint WHERE user_id = :user_id "
                "AND agent_id = :agent_id AND session_id = :session_id"
            )
            params = {"user_id": user_id, "agent_id": agent_id, "session_id": session_id}
        await get_management_db().execute_query(sql, params)

    async def mark_failed(
        self, user_id: int, agent_id: int, session_id: str, error: Exception
    ) -> None:
        await get_management_db().execute_query(
            "UPDATE agent_task_checkpoint SET status = 'failed', error_message = :error "
            "WHERE user_id = :user_id AND agent_id = :agent_id AND session_id = :session_id",
            {
                "user_id": user_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "error": str(error)[:1000],
            },
        )

    async def context(self, agent_id: int, datasource_id: int | None) -> dict[str, Any]:
        db = get_management_db()
        identity_rows = await db.execute_query(
            "SELECT a.id AS agent_id, a.updated_at AS agent_updated_at, "
            "a.chat_model_config_id, chat.updated_at AS chat_model_updated_at, "
            "a.embedding_model_config_id, emb.updated_at AS embedding_model_updated_at, "
            "a.semantic_domain_id, sd.updated_at AS semantic_domain_updated_at, "
            "ds.id AS datasource_id, ds.updated_at AS datasource_updated_at "
            "FROM agent a "
            "LEFT JOIN model_config chat ON chat.id = a.chat_model_config_id "
            "LEFT JOIN model_config emb ON emb.id = a.embedding_model_config_id "
            "LEFT JOIN semantic_domain sd ON sd.id = a.semantic_domain_id "
            "LEFT JOIN datasource ds ON ds.id = :datasource_id "
            "WHERE a.id = :agent_id",
            {"agent_id": agent_id, "datasource_id": datasource_id},
        )
        identity = identity_rows[0] if identity_rows else {
            "agent_id": agent_id,
            "datasource_id": datasource_id,
        }
        domain_id = identity.get("semantic_domain_id")
        semantic_versions = []
        if domain_id:
            semantic_versions = await db.execute_query(
                "SELECT 'concept' AS kind, COUNT(*) AS item_count, MAX(updated_at) AS latest "
                "FROM semantic_concept WHERE domain_id = :domain_id UNION ALL "
                "SELECT 'relation', COUNT(*), MAX(updated_at) FROM semantic_relation "
                "WHERE domain_id = :domain_id UNION ALL "
                "SELECT 'metric', COUNT(*), MAX(updated_at) FROM semantic_metric "
                "WHERE domain_id = :domain_id UNION ALL "
                "SELECT 'rule', COUNT(*), MAX(updated_at) FROM semantic_rule "
                "WHERE domain_id = :domain_id UNION ALL "
                "SELECT 'mapping', COUNT(*), MAX(updated_at) FROM semantic_mapping "
                "WHERE domain_id = :domain_id UNION ALL "
                "SELECT 'template', COUNT(*), MAX(updated_at) FROM logic_form_template "
                "WHERE domain_id = :domain_id",
                {"domain_id": domain_id},
            )
        schema_version = []
        if datasource_id:
            schema_version = await db.execute_query(
                "SELECT mt.id AS table_id, mt.table_name, mt.table_comment, mc.id AS column_id, "
                "mc.column_name, mc.data_type, mc.column_comment, mc.is_primary_key, "
                "mc.is_foreign_key, mc.foreign_key_ref "
                "FROM meta_table mt LEFT JOIN meta_column mc ON mc.table_id = mt.id "
                "WHERE mt.datasource_id = :datasource_id ORDER BY mt.id, mc.id",
                {"datasource_id": datasource_id},
            )
        fingerprint_source = {
            "identity": identity,
            "semantic": semantic_versions,
            "schema": schema_version,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_source, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
        return {
            "fingerprint": fingerprint,
            "datasource_id": datasource_id,
            "semantic_domain_id": domain_id,
            "chat_model_config_id": identity.get("chat_model_config_id"),
            "embedding_model_config_id": identity.get("embedding_model_config_id"),
        }

    async def prepare_turn(
        self,
        *,
        question: str,
        agent_id: int,
        user_id: int,
        session_id: str,
        datasource_id: int | None,
        trace_id: str,
        requested_mode: str | None = None,
        require_sql_confirmation: bool = False,
        enable_low_confidence_clarification: bool = False,
    ) -> dict[str, Any]:
        previous = await self.load(user_id, agent_id, session_id)
        context = await self.context(agent_id, datasource_id)
        state = reconcile_task_state(
            previous,
            question=question,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            datasource_id=datasource_id,
            trace_id=trace_id,
            context=context,
            requested_mode=requested_mode,
            require_sql_confirmation=require_sql_confirmation,
            enable_low_confidence_clarification=enable_low_confidence_clarification,
        )
        state["checkpoint_revision"] = await self.save(state)
        return state


_task_checkpoint_service: TaskCheckpointService | None = None


def get_task_checkpoint_service() -> TaskCheckpointService:
    global _task_checkpoint_service
    if _task_checkpoint_service is None:
        _task_checkpoint_service = TaskCheckpointService()
    return _task_checkpoint_service


__all__ = [
    "TURN_MODES",
    "CheckpointConflictError",
    "TaskCheckpointService",
    "checkpoint_payload",
    "classify_turn_mode",
    "get_task_checkpoint_service",
    "reconcile_task_state",
]
