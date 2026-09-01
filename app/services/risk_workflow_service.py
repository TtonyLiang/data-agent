"""Risk issue, evidence, review, and immutable report version workflow."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.db.mysql import get_management_db
from app.models.risk_workflow import (
    ChatRiskIssueCreatePayload,
    EvidenceCreatePayload,
    ReportCreatePayload,
    ReportFinalizePayload,
    ReportVersionCreatePayload,
    RiskIssueCreatePayload,
    RiskReviewPayload,
)
from app.services.decision_audit_service import (
    canonical_json,
    canonical_sha256,
    get_decision_audit_service,
)

JSON_FIELDS = {
    "detected_value",
    "expected_value",
    "source_context",
    "content",
    "before_state",
    "after_state",
    "issue_ids",
    "snapshot_json",
}

REVIEW_TRANSITIONS: dict[str, tuple[set[str], str]] = {
    "start_review": ({"open", "needs_info"}, "in_review"),
    "confirm": ({"open", "in_review", "needs_info"}, "confirmed"),
    "dismiss": ({"open", "in_review", "needs_info"}, "dismissed"),
    "request_info": ({"open", "in_review"}, "needs_info"),
    "resolve": ({"confirmed"}, "resolved"),
    "reopen": ({"needs_info", "confirmed", "dismissed", "resolved"}, "open"),
}


class RiskWorkflowNotFound(ValueError):
    pass


class RiskWorkflowConflict(ValueError):
    pass


def _loads(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def normalize_workflow_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for field in JSON_FIELDS:
        if field in normalized:
            fallback: Any = [] if field == "issue_ids" else {}
            if field in {"detected_value", "expected_value"}:
                fallback = None
            normalized[field] = _loads(normalized[field], fallback)
    return normalized


def review_target_status(current_status: str, action: str) -> str:
    transition = REVIEW_TRANSITIONS.get(action)
    if transition is None:
        raise ValueError(f"不支持的复核动作: {action}")
    allowed_statuses, target_status = transition
    if current_status not in allowed_statuses:
        raise RiskWorkflowConflict(
            f"风险事项状态 {current_status} 不允许执行 {action}"
        )
    return target_status


def _actor(user: dict[str, Any]) -> tuple[int | None, str]:
    actor_id = int(user["id"]) if user.get("id") is not None else None
    actor = str(user.get("username") or user.get("display_name") or actor_id or "unknown")
    return actor_id, actor


def _first(result: Any) -> dict[str, Any] | None:
    row = result.mappings().first()
    return dict(row) if row is not None else None


def _all(result: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in result.mappings().all()]


def _issue_state(issue: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_workflow_row(issue)
    fields = (
        "id",
        "domain_id",
        "ontology_release_id",
        "ontology_release_version",
        "ontology_release_hash",
        "subject_object_id",
        "issue_key",
        "category",
        "severity",
        "status",
        "title",
        "description",
        "rule_key",
        "detected_value",
        "expected_value",
        "source_context",
        "assignee",
        "version",
    )
    return {field: normalized.get(field) for field in fields}


def _evidence_state(evidence: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_workflow_row(evidence)
    fields = (
        "id",
        "ontology_release_id",
        "ontology_release_version",
        "ontology_release_hash",
        "evidence_type",
        "title",
        "description",
        "source_ref",
        "content",
        "trace_id",
        "checksum",
        "created_by",
        "created_at",
    )
    return {field: normalized.get(field) for field in fields}


def _review_state(review: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_workflow_row(review)
    fields = (
        "id",
        "ontology_release_id",
        "ontology_release_version",
        "ontology_release_hash",
        "review_action",
        "comment",
        "before_status",
        "after_status",
        "before_state",
        "after_state",
        "reviewer_id",
        "reviewer",
        "created_at",
    )
    return {field: normalized.get(field) for field in fields}


def _release_lineage(release: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(release["id"]),
        "version": int(release["version"]),
        "definition_hash": release.get("definition_hash"),
    }


def _report_summary(report_payload: Any) -> dict[str, Any] | None:
    report = _loads(report_payload, None)
    if not isinstance(report, dict):
        return None
    summary: dict[str, Any] = {}
    for key, limit in (("title", 512), ("summary", 4000), ("status", 128)):
        if report.get(key) is not None:
            summary[key] = str(report[key])[:limit]
    if report.get("row_count") is not None:
        summary["row_count"] = report["row_count"]
    return summary or None


def _bounded_artifact(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:500]
    if depth >= 2:
        try:
            return canonical_json(value)[:500]
        except ValueError:
            return str(value)[:500]
    if isinstance(value, list):
        return [_bounded_artifact(item, depth=depth + 1) for item in value[:8]]
    if isinstance(value, dict):
        return {
            str(key): _bounded_artifact(item, depth=depth + 1)
            for key, item in list(value.items())[:8]
        }
    return str(value)[:500]


def _selected_artifacts(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    payload = _loads(value, None)
    if not isinstance(payload, dict):
        return {}
    return {
        key: _bounded_artifact(payload[key])
        for key in keys
        if payload.get(key) not in (None, {}, [], "")
    }


def _metric_evidence_content(source: dict[str, Any], chat_history_id: int) -> dict[str, Any]:
    content = {
        "report": _selected_artifacts(
            source.get("report_payload"),
            ("title", "summary", "status", "row_count", "limitations"),
        ),
        "analysis": _selected_artifacts(
            source.get("python_result"),
            (
                "status",
                "analysis_mode",
                "row_count",
                "computed_items",
                "metrics",
                "insights",
                "limitations",
                "error",
            ),
        ),
        "plan": _selected_artifacts(
            source.get("plan_payload"),
            (
                "mode",
                "mode_label",
                "row_count",
                "analysis_steps",
                "metrics",
                "dimensions",
                "limitations",
            ),
        ),
        "chat_history_id": chat_history_id,
    }
    if len(canonical_json(content)) <= 32_000:
        return content
    return {
        "report": {
            **(_report_summary(source.get("report_payload")) or {}),
            "limitations": _selected_artifacts(
                source.get("report_payload"), ("limitations",)
            ).get("limitations", []),
        },
        "analysis": _selected_artifacts(
            source.get("python_result"),
            ("status", "analysis_mode", "row_count", "insights", "limitations", "error"),
        ),
        "plan": _selected_artifacts(
            source.get("plan_payload"), ("mode", "mode_label", "row_count")
        ),
        "chat_history_id": chat_history_id,
        "truncated": True,
    }


def _query_result_snapshot(value: Any) -> tuple[int, list[Any]]:
    result = _loads(value, None)
    if isinstance(result, list):
        if not result:
            raise ValueError("所选 assistant 消息没有查询结果，不能创建风险事项")
        return len(result), result[:50]
    if isinstance(result, dict):
        preview_rows = result.get("preview_rows")
        try:
            row_count = int(result.get("row_count") or 0)
        except (TypeError, ValueError):
            row_count = 0
        if row_count <= 0 or not isinstance(preview_rows, list) or not preview_rows:
            raise ValueError("所选 assistant 消息没有查询结果，不能创建风险事项")
        return row_count, preview_rows[:50]
    raise ValueError("所选 assistant 消息没有查询结果，不能创建风险事项")


class RiskWorkflowService:
    def __init__(self) -> None:
        self.audit = get_decision_audit_service()

    async def _require_current_release(self, session: Any, domain_id: int) -> dict[str, Any]:
        result = await session.execute(
            text(
                "SELECT id, version, name, definition_hash, created_at FROM ontology_release "
                "WHERE domain_id = :domain_id ORDER BY version DESC LIMIT 1"
            ),
            {"domain_id": domain_id},
        )
        release = _first(result)
        if release is None:
            raise ValueError("当前领域尚未发布 Ontology release，不能创建决策记录")
        return release

    async def _require_domain_agent(
        self, session: Any, domain_id: int, agent_id: int
    ) -> dict[str, Any]:
        result = await session.execute(
            text("SELECT id, agent_id FROM semantic_domain WHERE id = :domain_id"),
            {"domain_id": domain_id},
        )
        domain = _first(result)
        if domain is None:
            raise RiskWorkflowNotFound("Ontology 领域不存在")
        if int(domain["agent_id"]) != agent_id:
            raise ValueError("风险事项领域与问数智能体不一致")
        return domain

    async def _ensure_issue_key_available(
        self, session: Any, domain_id: int, issue_key: str
    ) -> None:
        duplicate = await session.execute(
            text(
                "SELECT id FROM risk_issue WHERE domain_id = :domain_id "
                "AND issue_key = :issue_key"
            ),
            {"domain_id": domain_id, "issue_key": issue_key},
        )
        if _first(duplicate) is not None:
            raise RiskWorkflowConflict(f"风险事项标识已存在: {issue_key}")

    async def _insert_issue_in_session(
        self,
        session: Any,
        *,
        data: dict[str, Any],
        release: dict[str, Any],
        actor_id: int | None,
        actor: str,
    ) -> dict[str, Any]:
        params = {
            **data,
            "ontology_release_id": int(release["id"]),
            "status": "open",
            "source_context": canonical_json(data.get("source_context") or {}),
            "detected_value": canonical_json(data.get("detected_value")),
            "expected_value": canonical_json(data.get("expected_value")),
            "created_by": actor_id,
        }
        inserted = await session.execute(
            text(
                "INSERT INTO risk_issue "
                "(domain_id, ontology_release_id, subject_object_id, issue_key, category, "
                "severity, status, title, description, rule_key, detected_value, "
                "expected_value, source_context, assignee, version, created_by) VALUES "
                "(:domain_id, :ontology_release_id, :subject_object_id, :issue_key, "
                ":category, :severity, :status, :title, :description, :rule_key, "
                ":detected_value, :expected_value, :source_context, :assignee, 1, :created_by)"
            ),
            params,
        )
        issue = {
            "id": int(inserted.lastrowid or 0),
            **data,
            "ontology_release_id": int(release["id"]),
            "ontology_release_version": int(release["version"]),
            "ontology_release_hash": release.get("definition_hash"),
            "status": "open",
            "version": 1,
            "created_by": actor_id,
        }
        await self.audit.append_in_session(
            session,
            domain_id=int(data["domain_id"]),
            event_type="issue.created",
            entity_type="risk_issue",
            entity_id=issue["id"],
            actor_id=actor_id,
            actor=actor,
            ontology_release_id=int(release["id"]),
            payload={
                "ontology_release": _release_lineage(release),
                "issue": _issue_state(issue),
            },
        )
        return issue

    async def _insert_evidence_in_session(
        self,
        session: Any,
        *,
        issue: dict[str, Any],
        payload: EvidenceCreatePayload,
        release: dict[str, Any],
        actor_id: int | None,
        actor: str,
    ) -> dict[str, Any]:
        domain_id = int(issue["domain_id"])
        issue_id = int(issue["id"])
        checksum = canonical_sha256(payload.content)
        inserted = await session.execute(
            text(
                "INSERT INTO risk_evidence "
                "(domain_id, issue_id, ontology_release_id, evidence_type, title, "
                "description, source_ref, content, trace_id, checksum, created_by) VALUES "
                "(:domain_id, :issue_id, :ontology_release_id, :evidence_type, :title, "
                ":description, :source_ref, :content, :trace_id, :checksum, :created_by)"
            ),
            {
                "domain_id": domain_id,
                "issue_id": issue_id,
                "ontology_release_id": int(release["id"]),
                **payload.model_dump(exclude={"content"}),
                "content": canonical_json(payload.content),
                "checksum": checksum,
                "created_by": actor_id,
            },
        )
        evidence = {
            "id": int(inserted.lastrowid or 0),
            "domain_id": domain_id,
            "issue_id": issue_id,
            "ontology_release_id": int(release["id"]),
            "ontology_release_version": int(release["version"]),
            "ontology_release_hash": release.get("definition_hash"),
            **payload.model_dump(),
            "checksum": checksum,
            "created_by": actor_id,
        }
        await self.audit.append_in_session(
            session,
            domain_id=domain_id,
            event_type="evidence.created",
            entity_type="risk_evidence",
            entity_id=evidence["id"],
            actor_id=actor_id,
            actor=actor,
            ontology_release_id=int(release["id"]),
            payload={
                "ontology_release": _release_lineage(release),
                "issue_id": issue_id,
                "issue_version": int(issue["version"]),
                "evidence_type": payload.evidence_type,
                "checksum": checksum,
                "source_ref": payload.source_ref,
                "trace_id": payload.trace_id,
            },
        )
        return evidence

    async def _load_chat_source(
        self,
        session: Any,
        payload: ChatRiskIssueCreatePayload,
        user: dict[str, Any],
    ) -> dict[str, Any]:
        filters = [
            "agent_id = :agent_id",
            "session_id = :session_id",
            "role = 'assistant'",
        ]
        params: dict[str, Any] = {
            "agent_id": payload.agent_id,
            "session_id": payload.session_id,
        }
        if user.get("role") != "admin":
            if user.get("id") is None:
                raise PermissionError("当前用户缺少有效身份")
            filters.append("user_id = :user_id")
            params["user_id"] = int(user["id"])
        result = await session.execute(
            text(
                "SELECT id, agent_id, user_id, session_id, content, logic_form, "
                "compiled_sql, sql_text, sql_result, execution_trace, plan_payload, "
                "semantic_check, python_result, report_payload, task_id, turn_id, created_at "
                "FROM chat_history WHERE "
                + " AND ".join(filters)
                + " ORDER BY id DESC"
            ),
            params,
        )
        candidates = _all(result)
        assistant: dict[str, Any] | None = None
        if payload.trace_id:
            for candidate in candidates:
                trace = _loads(candidate.get("execution_trace"), {})
                if isinstance(trace, dict) and str(trace.get("trace_id") or "") == payload.trace_id:
                    assistant = candidate
                    break
            if assistant is None:
                raise RiskWorkflowNotFound("未找到匹配 trace_id 的问数结果")
        elif candidates:
            assistant = candidates[0]
        if assistant is None:
            raise RiskWorkflowNotFound("当前会话没有可用的 assistant 问数结果")

        row_count, preview_rows = _query_result_snapshot(assistant.get("sql_result"))

        question_filters = [
            "agent_id = :agent_id",
            "session_id = :session_id",
            "role = 'user'",
            "id < :assistant_id",
        ]
        question_params = {
            "agent_id": payload.agent_id,
            "session_id": payload.session_id,
            "assistant_id": int(assistant["id"]),
        }
        if user.get("role") != "admin":
            question_filters.append("user_id = :question_user_id")
            question_params["question_user_id"] = int(user["id"])
        elif assistant.get("user_id") is not None:
            question_filters.append("user_id = :question_user_id")
            question_params["question_user_id"] = int(assistant["user_id"])
        question_result = await session.execute(
            text(
                "SELECT id, user_id, content, created_at FROM chat_history WHERE "
                + " AND ".join(question_filters)
                + " ORDER BY id DESC LIMIT 1"
            ),
            question_params,
        )
        question = _first(question_result)
        if question is None:
            raise RiskWorkflowNotFound("未找到该 assistant 结果对应的用户问题")

        execution_trace = _loads(assistant.get("execution_trace"), {})
        if not isinstance(execution_trace, dict):
            execution_trace = {}
        actual_trace_id = str(execution_trace.get("trace_id") or payload.trace_id or "") or None
        return {
            "assistant": assistant,
            "question": question,
            "row_count": row_count,
            "preview_rows": preview_rows,
            "logic_form": _loads(assistant.get("logic_form"), None),
            "execution_trace": execution_trace,
            "semantic_check": _loads(assistant.get("semantic_check"), None),
            "plan_payload": _loads(assistant.get("plan_payload"), None),
            "python_result": _loads(assistant.get("python_result"), None),
            "report_payload": _loads(assistant.get("report_payload"), None),
            "trace_id": actual_trace_id,
        }

    async def _load_subject_snapshot(
        self, session: Any, domain_id: int, object_id: int
    ) -> dict[str, Any]:
        result = await session.execute(
            text(
                "SELECT o.id, o.primary_value, o.display_name, o.properties, o.version, "
                "t.object_key AS object_type_key, t.name AS object_type_name "
                "FROM ontology_object o JOIN ontology_object_type t "
                "ON t.id = o.object_type_id "
                "WHERE o.id = :object_id AND o.domain_id = :domain_id"
            ),
            {"object_id": object_id, "domain_id": domain_id},
        )
        subject = _first(result)
        if subject is None:
            raise ValueError("风险事项绑定的 Ontology 对象不存在")
        subject["properties"] = _loads(subject.get("properties"), {})
        return subject

    async def _get_issue(
        self, session: Any, domain_id: int, issue_id: int, *, for_update: bool = False
    ) -> dict[str, Any]:
        suffix = " FOR UPDATE" if for_update else ""
        result = await session.execute(
            text(
                "SELECT i.*, r.version AS ontology_release_version, "
                "r.definition_hash AS ontology_release_hash "
                "FROM risk_issue i LEFT JOIN ontology_release r "
                "ON r.id = i.ontology_release_id "
                "WHERE i.id = :issue_id AND i.domain_id = :domain_id"
                + suffix
            ),
            {"issue_id": issue_id, "domain_id": domain_id},
        )
        issue = _first(result)
        if issue is None:
            raise RiskWorkflowNotFound("风险事项不存在")
        return normalize_workflow_row(issue)

    async def _get_report(
        self, session: Any, domain_id: int, report_id: int, *, for_update: bool = False
    ) -> dict[str, Any]:
        suffix = " FOR UPDATE" if for_update else ""
        result = await session.execute(
            text(
                "SELECT * FROM risk_report WHERE id = :report_id AND domain_id = :domain_id"
                + suffix
            ),
            {"report_id": report_id, "domain_id": domain_id},
        )
        report = _first(result)
        if report is None:
            raise RiskWorkflowNotFound("报告不存在")
        return normalize_workflow_row(report)

    async def _load_issues(
        self, session: Any, domain_id: int, issue_ids: list[int]
    ) -> list[dict[str, Any]]:
        if not issue_ids:
            return []
        params: dict[str, Any] = {"domain_id": domain_id}
        placeholders: list[str] = []
        for index, issue_id in enumerate(issue_ids):
            key = f"issue_{index}"
            placeholders.append(f":{key}")
            params[key] = issue_id
        result = await session.execute(
            text(
                "SELECT i.*, r.version AS ontology_release_version, "
                "r.definition_hash AS ontology_release_hash "
                "FROM risk_issue i LEFT JOIN ontology_release r "
                "ON r.id = i.ontology_release_id "
                "WHERE i.domain_id = :domain_id AND i.id IN ("
                + ", ".join(placeholders)
                + ")"
            ),
            params,
        )
        rows = [normalize_workflow_row(row) for row in _all(result)]
        by_id = {int(row["id"]): row for row in rows}
        missing = [issue_id for issue_id in issue_ids if issue_id not in by_id]
        if missing:
            raise ValueError(f"报告包含不存在或不属于当前领域的风险事项: {missing}")
        return [by_id[issue_id] for issue_id in issue_ids]

    async def _load_issue_snapshots(
        self,
        session: Any,
        domain_id: int,
        issues: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        issue_ids = [int(issue["id"]) for issue in issues]
        params: dict[str, Any] = {"domain_id": domain_id}
        placeholders: list[str] = []
        for index, issue_id in enumerate(issue_ids):
            key = f"snapshot_issue_{index}"
            placeholders.append(f":{key}")
            params[key] = issue_id
        evidence_result = await session.execute(
            text(
                "SELECT e.*, r.version AS ontology_release_version, "
                "r.definition_hash AS ontology_release_hash "
                "FROM risk_evidence e LEFT JOIN ontology_release r "
                "ON r.id = e.ontology_release_id "
                "WHERE e.domain_id = :domain_id AND e.issue_id IN ("
                + ", ".join(placeholders)
                + ") ORDER BY e.issue_id, e.created_at, e.id"
            ),
            params,
        )
        review_result = await session.execute(
            text(
                "SELECT v.*, r.version AS ontology_release_version, "
                "r.definition_hash AS ontology_release_hash "
                "FROM risk_issue_review v LEFT JOIN ontology_release r "
                "ON r.id = v.ontology_release_id "
                "WHERE v.domain_id = :domain_id AND v.issue_id IN ("
                + ", ".join(placeholders)
                + ") ORDER BY v.issue_id, v.created_at, v.id"
            ),
            params,
        )
        evidence_by_issue: dict[int, list[dict[str, Any]]] = {}
        for evidence in _all(evidence_result):
            evidence_by_issue.setdefault(int(evidence["issue_id"]), []).append(
                _evidence_state(evidence)
            )
        reviews_by_issue: dict[int, list[dict[str, Any]]] = {}
        for review in _all(review_result):
            reviews_by_issue.setdefault(int(review["issue_id"]), []).append(
                _review_state(review)
            )
        snapshots: list[dict[str, Any]] = []
        for issue in issues:
            issue_id = int(issue["id"])
            snapshots.append(
                {
                    **_issue_state(issue),
                    "evidence": evidence_by_issue.get(issue_id, []),
                    "reviews": reviews_by_issue.get(issue_id, []),
                }
            )
        return snapshots

    @staticmethod
    def _report_snapshot(
        report: dict[str, Any],
        issue_snapshots: list[dict[str, Any]],
        supplied: dict[str, Any],
        release: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "ontology_release": _release_lineage(release),
            "report": {
                "report_key": report["report_key"],
                "name": report["name"],
                "report_type": report["report_type"],
                "period_start": report.get("period_start"),
                "period_end": report.get("period_end"),
            },
            "issues": issue_snapshots,
            "context": supplied,
        }

    @staticmethod
    def _version_hash(
        *,
        report_id: int,
        version: int,
        ontology_release_id: int,
        issue_ids: list[int],
        snapshot: dict[str, Any],
        markdown: str,
    ) -> str:
        return canonical_sha256(
            {
                "report_id": report_id,
                "version": version,
                "ontology_release_id": ontology_release_id,
                "issue_ids": issue_ids,
                "snapshot": snapshot,
                "markdown": markdown,
            }
        )

    async def create_issue(
        self, payload: RiskIssueCreatePayload, user: dict[str, Any]
    ) -> dict[str, Any]:
        actor_id, actor = _actor(user)

        async def callback(session: Any) -> dict[str, Any]:
            release = await self._require_current_release(session, payload.domain_id)
            await self._ensure_issue_key_available(
                session, payload.domain_id, payload.issue_key
            )
            if payload.subject_object_id is not None:
                subject = await session.execute(
                    text(
                        "SELECT id FROM ontology_object WHERE id = :object_id "
                        "AND domain_id = :domain_id"
                    ),
                    {
                        "object_id": payload.subject_object_id,
                        "domain_id": payload.domain_id,
                    },
                )
                if _first(subject) is None:
                    raise ValueError("风险事项绑定的 Ontology 对象不存在")
            return await self._insert_issue_in_session(
                session,
                data=payload.model_dump(),
                release=release,
                actor_id=actor_id,
                actor=actor,
            )

        return await get_management_db().execute_in_transaction(callback)

    async def create_issue_from_chat(
        self, payload: ChatRiskIssueCreatePayload, user: dict[str, Any]
    ) -> dict[str, Any]:
        actor_id, actor = _actor(user)

        async def callback(session: Any) -> dict[str, Any]:
            await self._require_domain_agent(session, payload.domain_id, payload.agent_id)
            release = await self._require_current_release(session, payload.domain_id)
            await self._ensure_issue_key_available(
                session, payload.domain_id, payload.issue_key
            )
            source = await self._load_chat_source(session, payload, user)
            subject = None
            if payload.subject_object_id is not None:
                subject = await self._load_subject_snapshot(
                    session, payload.domain_id, payload.subject_object_id
                )

            assistant = source["assistant"]
            report_summary = _report_summary(source["report_payload"])
            detected_value: dict[str, Any] = {"row_count": source["row_count"]}
            if report_summary is not None:
                detected_value["report_summary"] = report_summary
            source_context = {
                "source_type": "chat_result",
                "agent_id": payload.agent_id,
                "session_id": payload.session_id,
                "chat_history_id": int(assistant["id"]),
                "trace_id": source["trace_id"],
                "task_id": assistant.get("task_id"),
                "turn_id": assistant.get("turn_id"),
            }
            issue = await self._insert_issue_in_session(
                session,
                data={
                    "domain_id": payload.domain_id,
                    "subject_object_id": payload.subject_object_id,
                    "issue_key": payload.issue_key,
                    "category": payload.category,
                    "severity": payload.severity,
                    "title": payload.title,
                    "description": payload.description,
                    "rule_key": payload.rule_key,
                    "detected_value": detected_value,
                    "expected_value": payload.expected_value,
                    "source_context": source_context,
                    "assignee": payload.assignee,
                },
                release=release,
                actor_id=actor_id,
                actor=actor,
            )

            chat_source_ref = (
                f"chat://agents/{payload.agent_id}/sessions/{payload.session_id}/"
                f"history/{assistant['id']}"
            )
            evidence_payloads = [
                EvidenceCreatePayload(
                    evidence_type="query",
                    title="问数查询结果",
                    source_ref=chat_source_ref,
                    trace_id=source["trace_id"],
                    content={
                        "question": source["question"]["content"],
                        "logic_form": source["logic_form"],
                        "compiled_sql": assistant.get("compiled_sql"),
                        "sql_text": assistant.get("sql_text"),
                        "row_count": source["row_count"],
                        "result_preview": source["preview_rows"],
                        "semantic_check": source["semantic_check"],
                        "chat_history_id": int(assistant["id"]),
                    },
                )
            ]
            if any(
                item not in (None, {}, [], "")
                for item in (
                    source["report_payload"],
                    source["python_result"],
                    source["plan_payload"],
                )
            ):
                evidence_payloads.append(
                    EvidenceCreatePayload(
                        evidence_type="metric",
                        title="问数分析产物",
                        source_ref=chat_source_ref,
                        trace_id=source["trace_id"],
                        content=_metric_evidence_content(
                            source, int(assistant["id"])
                        ),
                    )
                )
            if subject is not None:
                evidence_payloads.append(
                    EvidenceCreatePayload(
                        evidence_type="ontology_object",
                        title="Ontology 对象快照",
                        source_ref=f"ontology_object://{subject['id']}",
                        trace_id=source["trace_id"],
                        content={
                            "id": int(subject["id"]),
                            "object_type_key": subject["object_type_key"],
                            "object_type_name": subject.get("object_type_name"),
                            "primary_value": subject["primary_value"],
                            "display_name": subject["display_name"],
                            "properties": subject["properties"],
                            "version": int(subject["version"]),
                        },
                    )
                )

            evidence = [
                await self._insert_evidence_in_session(
                    session,
                    issue=issue,
                    payload=evidence_payload,
                    release=release,
                    actor_id=actor_id,
                    actor=actor,
                )
                for evidence_payload in evidence_payloads
            ]
            return {
                "issue": issue,
                "evidence": evidence,
                "source": source_context,
            }

        return await get_management_db().execute_in_transaction(callback)

    async def list_issues(
        self,
        domain_id: int,
        *,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        filters = ["i.domain_id = :domain_id"]
        params: dict[str, Any] = {"domain_id": domain_id, "limit": limit, "offset": offset}
        if status:
            filters.append("i.status = :status")
            params["status"] = status
        if severity:
            filters.append("i.severity = :severity")
            params["severity"] = severity
        rows = await get_management_db().execute_query(
            "SELECT i.*, r.version AS ontology_release_version, "
            "r.definition_hash AS ontology_release_hash, o.display_name AS subject_name, "
            "t.name AS subject_type, "
            "(SELECT COUNT(*) FROM risk_evidence e WHERE e.issue_id = i.id) "
            "AS evidence_count, "
            "(SELECT COUNT(*) FROM risk_issue_review v WHERE v.issue_id = i.id) "
            "AS review_count "
            "FROM risk_issue i LEFT JOIN ontology_release r ON r.id = i.ontology_release_id "
            "LEFT JOIN ontology_object o ON o.id = i.subject_object_id "
            "LEFT JOIN ontology_object_type t ON t.id = o.object_type_id "
            "WHERE "
            + " AND ".join(filters)
            + " ORDER BY i.updated_at DESC, i.id DESC LIMIT :limit OFFSET :offset",
            params,
        )
        return [normalize_workflow_row(row) for row in rows]

    async def get_issue(self, domain_id: int, issue_id: int) -> dict[str, Any]:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT i.*, r.version AS ontology_release_version, "
            "r.definition_hash AS ontology_release_hash, o.display_name AS subject_name, "
            "t.name AS subject_type "
            "FROM risk_issue i LEFT JOIN ontology_release r ON r.id = i.ontology_release_id "
            "LEFT JOIN ontology_object o ON o.id = i.subject_object_id "
            "LEFT JOIN ontology_object_type t ON t.id = o.object_type_id "
            "WHERE i.id = :issue_id AND i.domain_id = :domain_id",
            {"issue_id": issue_id, "domain_id": domain_id},
        )
        if not rows:
            raise RiskWorkflowNotFound("风险事项不存在")
        evidence = await db.execute_query(
            "SELECT e.*, r.version AS ontology_release_version, "
            "r.definition_hash AS ontology_release_hash "
            "FROM risk_evidence e LEFT JOIN ontology_release r "
            "ON r.id = e.ontology_release_id "
            "WHERE e.issue_id = :issue_id AND e.domain_id = :domain_id "
            "ORDER BY e.created_at ASC, e.id ASC",
            {"issue_id": issue_id, "domain_id": domain_id},
        )
        reviews = await db.execute_query(
            "SELECT v.*, r.version AS ontology_release_version, "
            "r.definition_hash AS ontology_release_hash "
            "FROM risk_issue_review v LEFT JOIN ontology_release r "
            "ON r.id = v.ontology_release_id "
            "WHERE v.issue_id = :issue_id AND v.domain_id = :domain_id "
            "ORDER BY v.created_at ASC, v.id ASC",
            {"issue_id": issue_id, "domain_id": domain_id},
        )
        return {
            **normalize_workflow_row(rows[0]),
            "evidence": [normalize_workflow_row(row) for row in evidence],
            "reviews": [normalize_workflow_row(row) for row in reviews],
        }

    async def add_evidence(
        self,
        domain_id: int,
        issue_id: int,
        payload: EvidenceCreatePayload,
        user: dict[str, Any],
    ) -> dict[str, Any]:
        actor_id, actor = _actor(user)

        async def callback(session: Any) -> dict[str, Any]:
            issue = await self._get_issue(session, domain_id, issue_id, for_update=True)
            release = await self._require_current_release(session, domain_id)
            return await self._insert_evidence_in_session(
                session,
                issue=issue,
                payload=payload,
                release=release,
                actor_id=actor_id,
                actor=actor,
            )

        return await get_management_db().execute_in_transaction(callback)

    async def review_issue(
        self,
        domain_id: int,
        issue_id: int,
        payload: RiskReviewPayload,
        user: dict[str, Any],
    ) -> dict[str, Any]:
        actor_id, actor = _actor(user)

        async def callback(session: Any) -> dict[str, Any]:
            issue = await self._get_issue(session, domain_id, issue_id, for_update=True)
            release = await self._require_current_release(session, domain_id)
            current_version = int(issue["version"])
            if user.get("role") != "admin":
                if issue.get("created_by") is not None and int(issue["created_by"]) == actor_id:
                    raise PermissionError("风险事项创建人不能复核自己的事项")
                assignee = str(issue.get("assignee") or "").strip()
                identities = {
                    str(user.get("username") or "").strip(),
                    str(user.get("display_name") or "").strip(),
                }
                identities.discard("")
                if not assignee or assignee not in identities:
                    raise PermissionError("当前用户不是该风险事项的指派复核人")
            if payload.expected_version is not None and payload.expected_version != current_version:
                raise RiskWorkflowConflict(
                    f"风险事项版本已变化: 期望 {payload.expected_version}, 当前 {current_version}"
                )
            target_status = review_target_status(str(issue["status"]), payload.action)
            before_state = _issue_state(issue)
            after_state = {**before_state, "status": target_status, "version": current_version + 1}
            updated = await session.execute(
                text(
                    "UPDATE risk_issue SET status = :status, version = version + 1 "
                    "WHERE id = :issue_id AND domain_id = :domain_id AND version = :version"
                ),
                {
                    "status": target_status,
                    "issue_id": issue_id,
                    "domain_id": domain_id,
                    "version": current_version,
                },
            )
            if updated.rowcount != 1:
                raise RiskWorkflowConflict("风险事项版本已变化，请刷新后重试")
            review_insert = await session.execute(
                text(
                    "INSERT INTO risk_issue_review "
                    "(domain_id, issue_id, ontology_release_id, review_action, before_status, "
                    "after_status, before_state, after_state, reviewer_id, reviewer, comment) "
                    "VALUES (:domain_id, :issue_id, :ontology_release_id, :review_action, "
                    ":before_status, :after_status, :before_state, :after_state, :reviewer_id, "
                    ":reviewer, :comment)"
                ),
                {
                    "domain_id": domain_id,
                    "issue_id": issue_id,
                    "ontology_release_id": int(release["id"]),
                    "review_action": payload.action,
                    "before_status": issue["status"],
                    "after_status": target_status,
                    "before_state": canonical_json(before_state),
                    "after_state": canonical_json(after_state),
                    "reviewer_id": actor_id,
                    "reviewer": actor,
                    "comment": payload.comment,
                },
            )
            review = {
                "id": int(review_insert.lastrowid or 0),
                "domain_id": domain_id,
                "issue_id": issue_id,
                "ontology_release_id": int(release["id"]),
                "ontology_release_version": int(release["version"]),
                "ontology_release_hash": release.get("definition_hash"),
                "review_action": payload.action,
                "before_status": issue["status"],
                "after_status": target_status,
                "before_state": before_state,
                "after_state": after_state,
                "reviewer_id": actor_id,
                "reviewer": actor,
                "comment": payload.comment,
            }
            await self.audit.append_in_session(
                session,
                domain_id=domain_id,
                event_type="issue.reviewed",
                entity_type="risk_issue",
                entity_id=issue_id,
                actor_id=actor_id,
                actor=actor,
                ontology_release_id=int(release["id"]),
                payload={
                    "ontology_release": _release_lineage(release),
                    "review_id": review["id"],
                    "action": payload.action,
                    "comment": payload.comment,
                    "before_state": before_state,
                    "after_state": after_state,
                },
            )
            return {"issue": after_state, "review": review}

        return await get_management_db().execute_in_transaction(callback)

    async def create_report(
        self, payload: ReportCreatePayload, user: dict[str, Any]
    ) -> dict[str, Any]:
        if payload.status != "draft":
            raise ValueError("新报告只能以 draft 状态创建")
        actor_id, actor = _actor(user)

        async def callback(session: Any) -> dict[str, Any]:
            release = await self._require_current_release(session, payload.domain_id)
            duplicate = await session.execute(
                text(
                    "SELECT id FROM risk_report WHERE domain_id = :domain_id "
                    "AND report_key = :report_key"
                ),
                {"domain_id": payload.domain_id, "report_key": payload.report_key},
            )
            if _first(duplicate) is not None:
                raise RiskWorkflowConflict(f"报告标识已存在: {payload.report_key}")
            issues = await self._load_issues(session, payload.domain_id, payload.issue_ids)
            issue_snapshots = await self._load_issue_snapshots(
                session, payload.domain_id, issues
            )
            report_insert = await session.execute(
                text(
                    "INSERT INTO risk_report "
                    "(domain_id, report_key, name, report_type, period_start, period_end, status, "
                    "current_version, created_by) VALUES (:domain_id, :report_key, :name, "
                    ":report_type, :period_start, :period_end, 'draft', 1, :created_by)"
                ),
                {
                    "domain_id": payload.domain_id,
                    "report_key": payload.report_key,
                    "name": payload.name,
                    "report_type": payload.report_type,
                    "period_start": payload.period_start,
                    "period_end": payload.period_end,
                    "created_by": actor_id,
                },
            )
            report = {
                "id": int(report_insert.lastrowid or 0),
                "domain_id": payload.domain_id,
                "report_key": payload.report_key,
                "name": payload.name,
                "report_type": payload.report_type,
                "period_start": payload.period_start,
                "period_end": payload.period_end,
                "status": "draft",
                "current_version": 1,
                "created_by": actor_id,
            }
            snapshot = self._report_snapshot(
                report, issue_snapshots, payload.snapshot, release
            )
            content_hash = self._version_hash(
                report_id=report["id"],
                version=1,
                ontology_release_id=int(release["id"]),
                issue_ids=payload.issue_ids,
                snapshot=snapshot,
                markdown=payload.markdown,
            )
            version_insert = await session.execute(
                text(
                    "INSERT INTO risk_report_version "
                    "(report_id, domain_id, version, ontology_release_id, issue_ids, "
                    "snapshot_json, markdown, content_hash, created_by) VALUES "
                    "(:report_id, :domain_id, 1, :ontology_release_id, :issue_ids, "
                    ":snapshot_json, :markdown, :content_hash, :created_by)"
                ),
                {
                    "report_id": report["id"],
                    "domain_id": payload.domain_id,
                    "ontology_release_id": int(release["id"]),
                    "issue_ids": canonical_json(payload.issue_ids),
                    "snapshot_json": canonical_json(snapshot),
                    "markdown": payload.markdown,
                    "content_hash": content_hash,
                    "created_by": actor_id,
                },
            )
            version = {
                "id": int(version_insert.lastrowid or 0),
                "report_id": report["id"],
                "domain_id": payload.domain_id,
                "version": 1,
                "ontology_release_id": int(release["id"]),
                "ontology_release_version": int(release["version"]),
                "ontology_release_hash": release.get("definition_hash"),
                "issue_ids": payload.issue_ids,
                "snapshot_json": snapshot,
                "markdown": payload.markdown,
                "content_hash": content_hash,
                "created_by": actor_id,
            }
            await self.audit.append_in_session(
                session,
                domain_id=payload.domain_id,
                event_type="report.created",
                entity_type="risk_report",
                entity_id=report["id"],
                actor_id=actor_id,
                actor=actor,
                ontology_release_id=int(release["id"]),
                payload={
                    "ontology_release": _release_lineage(release),
                    "report": report,
                },
            )
            await self.audit.append_in_session(
                session,
                domain_id=payload.domain_id,
                event_type="report.version.created",
                entity_type="risk_report_version",
                entity_id=version["id"],
                actor_id=actor_id,
                actor=actor,
                ontology_release_id=int(release["id"]),
                payload={
                    "ontology_release": _release_lineage(release),
                    "report_id": report["id"],
                    "version": 1,
                    "issue_ids": payload.issue_ids,
                    "content_hash": content_hash,
                },
            )
            return {"report": report, "version": version}

        return await get_management_db().execute_in_transaction(callback)

    async def create_report_version(
        self,
        domain_id: int,
        report_id: int,
        payload: ReportVersionCreatePayload,
        user: dict[str, Any],
    ) -> dict[str, Any]:
        actor_id, actor = _actor(user)

        async def callback(session: Any) -> dict[str, Any]:
            report = await self._get_report(session, domain_id, report_id, for_update=True)
            if report["status"] != "draft":
                raise RiskWorkflowConflict("已定稿报告不能创建新版本")
            current_version = int(report["current_version"])
            if (
                payload.expected_current_version is not None
                and payload.expected_current_version != current_version
            ):
                raise RiskWorkflowConflict(
                    f"报告版本已变化: 期望 {payload.expected_current_version}, "
                    f"当前 {current_version}"
                )
            release = await self._require_current_release(session, domain_id)
            issues = await self._load_issues(session, domain_id, payload.issue_ids)
            issue_snapshots = await self._load_issue_snapshots(session, domain_id, issues)
            version_number = current_version + 1
            snapshot = self._report_snapshot(
                report, issue_snapshots, payload.snapshot, release
            )
            content_hash = self._version_hash(
                report_id=report_id,
                version=version_number,
                ontology_release_id=int(release["id"]),
                issue_ids=payload.issue_ids,
                snapshot=snapshot,
                markdown=payload.markdown,
            )
            version_insert = await session.execute(
                text(
                    "INSERT INTO risk_report_version "
                    "(report_id, domain_id, version, ontology_release_id, issue_ids, "
                    "snapshot_json, markdown, content_hash, created_by) VALUES "
                    "(:report_id, :domain_id, :version, :ontology_release_id, :issue_ids, "
                    ":snapshot_json, :markdown, :content_hash, :created_by)"
                ),
                {
                    "report_id": report_id,
                    "domain_id": domain_id,
                    "version": version_number,
                    "ontology_release_id": int(release["id"]),
                    "issue_ids": canonical_json(payload.issue_ids),
                    "snapshot_json": canonical_json(snapshot),
                    "markdown": payload.markdown,
                    "content_hash": content_hash,
                    "created_by": actor_id,
                },
            )
            updated = await session.execute(
                text(
                    "UPDATE risk_report SET current_version = :new_version "
                    "WHERE id = :report_id AND domain_id = :domain_id "
                    "AND current_version = :current_version AND status = 'draft'"
                ),
                {
                    "new_version": version_number,
                    "report_id": report_id,
                    "domain_id": domain_id,
                    "current_version": current_version,
                },
            )
            if updated.rowcount != 1:
                raise RiskWorkflowConflict("报告版本已变化，请刷新后重试")
            version = {
                "id": int(version_insert.lastrowid or 0),
                "report_id": report_id,
                "domain_id": domain_id,
                "version": version_number,
                "ontology_release_id": int(release["id"]),
                "ontology_release_version": int(release["version"]),
                "ontology_release_hash": release.get("definition_hash"),
                "issue_ids": payload.issue_ids,
                "snapshot_json": snapshot,
                "markdown": payload.markdown,
                "content_hash": content_hash,
                "created_by": actor_id,
            }
            await self.audit.append_in_session(
                session,
                domain_id=domain_id,
                event_type="report.version.created",
                entity_type="risk_report_version",
                entity_id=version["id"],
                actor_id=actor_id,
                actor=actor,
                ontology_release_id=int(release["id"]),
                payload={
                    "ontology_release": _release_lineage(release),
                    "report_id": report_id,
                    "version": version_number,
                    "issue_ids": payload.issue_ids,
                    "content_hash": content_hash,
                },
            )
            return version

        return await get_management_db().execute_in_transaction(callback)

    async def finalize_report(
        self,
        domain_id: int,
        report_id: int,
        payload: ReportFinalizePayload,
        user: dict[str, Any],
    ) -> dict[str, Any]:
        actor_id, actor = _actor(user)

        async def callback(session: Any) -> dict[str, Any]:
            report = await self._get_report(session, domain_id, report_id, for_update=True)
            if report["status"] == "finalized":
                raise RiskWorkflowConflict("报告已经定稿")
            current_version = int(report["current_version"])
            if payload.expected_version is not None and payload.expected_version != current_version:
                raise RiskWorkflowConflict(
                    f"报告版本已变化: 期望 {payload.expected_version}, 当前 {current_version}"
                )
            release = await self._require_current_release(session, domain_id)
            version_result = await session.execute(
                text(
                    "SELECT id, ontology_release_id, content_hash FROM risk_report_version "
                    "WHERE report_id = :report_id AND domain_id = :domain_id "
                    "AND version = :version"
                ),
                {"report_id": report_id, "domain_id": domain_id, "version": current_version},
            )
            version = _first(version_result)
            if version is None:
                raise RiskWorkflowConflict("报告当前版本不存在，不能定稿")
            updated = await session.execute(
                text(
                    "UPDATE risk_report SET status = 'finalized', finalized_by = :user_id, "
                    "finalized_at = CURRENT_TIMESTAMP WHERE id = :report_id "
                    "AND domain_id = :domain_id AND status = 'draft'"
                ),
                {"user_id": actor_id, "report_id": report_id, "domain_id": domain_id},
            )
            if updated.rowcount != 1:
                raise RiskWorkflowConflict("报告状态已变化，请刷新后重试")
            await self.audit.append_in_session(
                session,
                domain_id=domain_id,
                event_type="report.finalized",
                entity_type="risk_report",
                entity_id=report_id,
                actor_id=actor_id,
                actor=actor,
                ontology_release_id=int(release["id"]),
                payload={
                    "ontology_release": _release_lineage(release),
                    "version_id": int(version["id"]),
                    "version": current_version,
                    "version_release_id": int(version["ontology_release_id"]),
                    "content_hash": version["content_hash"],
                },
            )
            return {
                **report,
                "status": "finalized",
                "finalized_by": actor_id,
                "finalized_version": current_version,
                "content_hash": version["content_hash"],
                "finalized_under_release_id": int(release["id"]),
                "finalized_under_release_version": int(release["version"]),
                "finalized_under_release_hash": release.get("definition_hash"),
            }

        return await get_management_db().execute_in_transaction(callback)

    async def list_reports(
        self, domain_id: int, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        rows = await get_management_db().execute_query(
            "SELECT p.*, v.id AS current_version_id, v.content_hash AS current_content_hash, "
            "v.ontology_release_id, r.version AS ontology_release_version, "
            "r.definition_hash AS ontology_release_hash "
            "FROM risk_report p LEFT JOIN risk_report_version v "
            "ON v.report_id = p.id AND v.version = p.current_version "
            "LEFT JOIN ontology_release r ON r.id = v.ontology_release_id "
            "WHERE p.domain_id = :domain_id "
            "ORDER BY p.updated_at DESC, p.id DESC LIMIT :limit OFFSET :offset",
            {"domain_id": domain_id, "limit": limit, "offset": offset},
        )
        return [normalize_workflow_row(row) for row in rows]

    async def list_report_versions(
        self, domain_id: int, report_id: int
    ) -> list[dict[str, Any]]:
        report_rows = await get_management_db().execute_query(
            "SELECT id FROM risk_report WHERE id = :report_id AND domain_id = :domain_id",
            {"report_id": report_id, "domain_id": domain_id},
        )
        if not report_rows:
            raise RiskWorkflowNotFound("报告不存在")
        rows = await get_management_db().execute_query(
            "SELECT v.*, r.version AS ontology_release_version, "
            "r.definition_hash AS ontology_release_hash "
            "FROM risk_report_version v LEFT JOIN ontology_release r "
            "ON r.id = v.ontology_release_id "
            "WHERE v.report_id = :report_id AND v.domain_id = :domain_id "
            "ORDER BY v.version DESC",
            {"report_id": report_id, "domain_id": domain_id},
        )
        return [normalize_workflow_row(row) for row in rows]

    async def get_summary(self, domain_id: int) -> dict[str, Any]:
        db = get_management_db()
        release_rows = await db.execute_query(
            "SELECT id, version, name, definition_hash, created_at FROM ontology_release "
            "WHERE domain_id = :domain_id ORDER BY version DESC LIMIT 1",
            {"domain_id": domain_id},
        )
        issue_rows = await db.execute_query(
            "SELECT status, severity, COUNT(*) AS count FROM risk_issue "
            "WHERE domain_id = :domain_id GROUP BY status, severity",
            {"domain_id": domain_id},
        )
        report_rows = await db.execute_query(
            "SELECT status, COUNT(*) AS count FROM risk_report WHERE domain_id = :domain_id "
            "GROUP BY status",
            {"domain_id": domain_id},
        )
        audit_rows = await db.execute_query(
            "SELECT COUNT(*) AS count FROM decision_audit_event WHERE domain_id = :domain_id",
            {"domain_id": domain_id},
        )
        issue_by_status: dict[str, int] = {}
        issue_by_severity: dict[str, int] = {}
        for row in issue_rows:
            count = int(row["count"])
            issue_by_status[str(row["status"])] = issue_by_status.get(str(row["status"]), 0) + count
            issue_by_severity[str(row["severity"])] = (
                issue_by_severity.get(str(row["severity"]), 0) + count
            )
        report_by_status = {
            str(row["status"]): int(row["count"]) for row in report_rows
        }
        issue_total = sum(issue_by_status.values())
        report_total = sum(report_by_status.values())
        pending_review = sum(
            issue_by_status.get(status, 0)
            for status in ("open", "in_review", "needs_info")
        )
        return {
            "domain_id": domain_id,
            "latest_release": release_rows[0] if release_rows else None,
            "counts": {
                "issues": issue_total,
                "open_issues": issue_by_status.get("open", 0),
                "high_risk_issues": (
                    issue_by_severity.get("high", 0)
                    + issue_by_severity.get("critical", 0)
                ),
                "pending_review": pending_review,
                "reports": report_total,
                "audit_events": int(audit_rows[0]["count"]) if audit_rows else 0,
            },
            "status_counts": issue_by_status,
            "severity_counts": issue_by_severity,
            "report_status_counts": report_by_status,
        }


_risk_workflow_service: RiskWorkflowService | None = None


def get_risk_workflow_service() -> RiskWorkflowService:
    global _risk_workflow_service
    if _risk_workflow_service is None:
        _risk_workflow_service = RiskWorkflowService()
    return _risk_workflow_service
