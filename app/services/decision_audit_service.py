"""Append-only, hash-chained audit events for governed business decisions."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.db.mysql import get_management_db


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"不支持的 JSON 值类型: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize JSON with stable key ordering for hashes and persisted snapshots."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=_json_default,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"内容不是可规范化的 JSON: {exc}") from exc


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def audit_event_body(
    *,
    domain_id: int,
    sequence_no: int,
    event_type: str,
    entity_type: str,
    entity_id: int | None,
    actor_id: int | None,
    actor: str | None,
    ontology_release_id: int | None,
    recorded_at: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "domain_id": int(domain_id),
        "sequence_no": int(sequence_no),
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": int(entity_id) if entity_id is not None else None,
        "actor_id": int(actor_id) if actor_id is not None else None,
        "actor": actor,
        "ontology_release_id": (
            int(ontology_release_id) if ontology_release_id is not None else None
        ),
        "recorded_at": recorded_at,
        "payload": payload,
    }


def compute_event_hash(previous_hash: str | None, body: dict[str, Any]) -> str:
    return canonical_sha256({"previous_hash": previous_hash, "event": body})


def normalize_audit_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    stored = _loads(normalized.pop("payload_json", None), {})
    if isinstance(stored, dict) and "recorded_at" in stored and "payload" in stored:
        normalized["recorded_at"] = stored["recorded_at"]
        normalized["payload"] = stored["payload"]
    else:
        normalized["recorded_at"] = normalized.get("created_at")
        normalized["payload"] = stored
    return normalized


class DecisionAuditService:
    async def append_in_session(
        self,
        session: Any,
        *,
        domain_id: int,
        event_type: str,
        entity_type: str,
        entity_id: int | None,
        actor_id: int | None,
        actor: str | None,
        ontology_release_id: int | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Append one event while holding the domain row lock.

        Locking ``semantic_domain`` serializes both the empty-chain case and
        normal appends, so two concurrent writers cannot claim the same
        per-domain sequence number.
        """
        domain_result = await session.execute(
            text("SELECT id FROM semantic_domain WHERE id = :domain_id FOR UPDATE"),
            {"domain_id": domain_id},
        )
        if domain_result.mappings().first() is None:
            raise ValueError("Ontology 领域不存在")

        head_result = await session.execute(
            text(
                "SELECT event_count, head_hash FROM decision_audit_head "
                "WHERE domain_id = :domain_id FOR UPDATE"
            ),
            {"domain_id": domain_id},
        )
        head = head_result.mappings().first()
        sequence_no = int(head["event_count"]) + 1 if head else 1
        previous_hash = str(head["head_hash"]) if head and head["head_hash"] else None
        recorded_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        body = audit_event_body(
            domain_id=domain_id,
            sequence_no=sequence_no,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            actor=actor,
            ontology_release_id=ontology_release_id,
            recorded_at=recorded_at,
            payload=payload,
        )
        event_hash = compute_event_hash(previous_hash, body)
        inserted = await session.execute(
            text(
                "INSERT INTO decision_audit_event "
                "(domain_id, sequence_no, event_type, entity_type, entity_id, actor_id, actor, "
                "ontology_release_id, payload_json, previous_hash, event_hash) VALUES "
                "(:domain_id, :sequence_no, :event_type, :entity_type, :entity_id, :actor_id, "
                ":actor, :ontology_release_id, :payload_json, :previous_hash, :event_hash)"
            ),
            {
                **body,
                "payload_json": canonical_json(
                    {"recorded_at": recorded_at, "payload": payload}
                ),
                "previous_hash": previous_hash,
                "event_hash": event_hash,
            },
        )
        await session.execute(
            text(
                "INSERT INTO decision_audit_head (domain_id, event_count, head_hash) "
                "VALUES (:domain_id, :event_count, :head_hash) "
                "ON DUPLICATE KEY UPDATE event_count = VALUES(event_count), "
                "head_hash = VALUES(head_hash), updated_at = CURRENT_TIMESTAMP"
            ),
            {
                "domain_id": domain_id,
                "event_count": sequence_no,
                "head_hash": event_hash,
            },
        )
        return {
            "id": int(inserted.lastrowid or 0),
            **body,
            "previous_hash": previous_hash,
            "event_hash": event_hash,
        }

    async def append(self, **kwargs: Any) -> dict[str, Any]:
        async def callback(session: Any) -> dict[str, Any]:
            return await self.append_in_session(session, **kwargs)

        return await get_management_db().execute_in_transaction(callback)

    async def list_events(
        self, domain_id: int, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        rows = await get_management_db().execute_query(
            "SELECT e.*, r.version AS ontology_release_version, "
            "r.definition_hash AS ontology_release_hash "
            "FROM decision_audit_event e "
            "LEFT JOIN ontology_release r ON r.id = e.ontology_release_id "
            "WHERE e.domain_id = :domain_id "
            "ORDER BY e.sequence_no DESC LIMIT :limit OFFSET :offset",
            {"domain_id": domain_id, "limit": limit, "offset": offset},
        )
        return [normalize_audit_row(row) for row in rows]

    async def verify_chain(self, domain_id: int) -> dict[str, Any]:
        db = get_management_db()
        rows = await db.execute_query(
            "SELECT * FROM decision_audit_event WHERE domain_id = :domain_id "
            "ORDER BY sequence_no ASC",
            {"domain_id": domain_id},
        )
        head_rows = await db.execute_query(
            "SELECT event_count, head_hash FROM decision_audit_head WHERE domain_id = :domain_id",
            {"domain_id": domain_id},
        )
        if not head_rows:
            if not rows:
                return {
                    "valid": True,
                    "checked_events": 0,
                    "head_hash": None,
                    "broken_event_id": None,
                    "reason": None,
                }
            return {
                "valid": False,
                "checked_events": 0,
                "head_hash": None,
                "broken_event_id": rows[0].get("id"),
                "reason": "审计链头锚点缺失",
            }
        anchored_count = int(head_rows[0].get("event_count") or 0)
        anchored_hash = head_rows[0].get("head_hash")
        previous_hash: str | None = None
        for expected_sequence, raw_row in enumerate(rows, start=1):
            row = normalize_audit_row(raw_row)
            sequence_no = int(row["sequence_no"])
            if sequence_no != expected_sequence:
                return {
                    "valid": False,
                    "checked_events": expected_sequence - 1,
                    "broken_event_id": row.get("id"),
                    "head_hash": previous_hash,
                    "reason": (
                        f"审计序号不连续: 期望 {expected_sequence}, 实际 {sequence_no}"
                    ),
                }
            if row.get("previous_hash") != previous_hash:
                return {
                    "valid": False,
                    "checked_events": expected_sequence - 1,
                    "broken_event_id": row.get("id"),
                    "head_hash": previous_hash,
                    "reason": "previous_hash 与前一事件不一致",
                }
            body = audit_event_body(
                domain_id=int(row["domain_id"]),
                sequence_no=sequence_no,
                event_type=str(row["event_type"]),
                entity_type=str(row["entity_type"]),
                entity_id=(int(row["entity_id"]) if row.get("entity_id") is not None else None),
                actor_id=(int(row["actor_id"]) if row.get("actor_id") is not None else None),
                actor=row.get("actor"),
                ontology_release_id=(
                    int(row["ontology_release_id"])
                    if row.get("ontology_release_id") is not None
                    else None
                ),
                recorded_at=str(row["recorded_at"]),
                payload=row["payload"],
            )
            expected_hash = compute_event_hash(previous_hash, body)
            if row.get("event_hash") != expected_hash:
                return {
                    "valid": False,
                    "checked_events": expected_sequence - 1,
                    "broken_event_id": row.get("id"),
                    "head_hash": previous_hash,
                    "reason": "event_hash 校验失败",
                }
            previous_hash = expected_hash
        if len(rows) != anchored_count:
            return {
                "valid": False,
                "checked_events": len(rows),
                "broken_event_id": None,
                "head_hash": anchored_hash,
                "reason": f"审计事件数量与链头锚点不一致: {len(rows)} != {anchored_count}",
            }
        if previous_hash != anchored_hash:
            return {
                "valid": False,
                "checked_events": len(rows),
                "broken_event_id": rows[-1].get("id") if rows else None,
                "head_hash": anchored_hash,
                "reason": "审计链尾哈希与链头锚点不一致",
            }
        return {
            "valid": True,
            "checked_events": len(rows),
            "head_hash": anchored_hash,
            "broken_event_id": None,
            "reason": None,
        }


_decision_audit_service: DecisionAuditService | None = None


def get_decision_audit_service() -> DecisionAuditService:
    global _decision_audit_service
    if _decision_audit_service is None:
        _decision_audit_service = DecisionAuditService()
    return _decision_audit_service
