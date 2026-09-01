import hashlib
import json

import pytest

from app.db import migrations
from app.db.ontology_schema import ONTOLOGY_TABLE_STATEMENTS


class ReleaseDB:
    def __init__(self):
        self.updates: list[dict] = []

    async def execute_query(self, sql: str, params: dict | None = None):
        if sql.startswith("SELECT id, definition_json"):
            return [
                {
                    "id": 11,
                    "definition_json": '{"objects":[2,1],"domain":{"key":"loan"}}',
                }
            ]
        if sql.startswith("UPDATE ontology_release"):
            self.updates.append(params or {})
        return []


def test_ontology_schema_binds_actions_to_release_and_hashes_definitions():
    ddl = "\n".join(ONTOLOGY_TABLE_STATEMENTS)

    assert "ontology_release_id BIGINT" in ddl
    assert "definition_hash CHAR(64)" in ddl
    assert "idx_ontology_run_release" in ddl


@pytest.mark.asyncio
async def test_existing_release_hashes_are_backfilled_deterministically(monkeypatch):
    db = ReleaseDB()
    monkeypatch.setattr(migrations, "get_management_db", lambda: db)

    await migrations.backfill_ontology_release_hashes()

    canonical = json.dumps(
        {"objects": [2, 1], "domain": {"key": "loan"}},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert db.updates == [{"id": 11, "definition_hash": expected}]


@pytest.mark.asyncio
async def test_existing_audit_events_receive_a_chain_head_anchor(monkeypatch):
    class AuditHeadDB:
        def __init__(self):
            self.inserted = []

        async def execute_query(self, sql: str, params: dict | None = None):
            if sql.startswith("SELECT DISTINCT domain_id"):
                return [{"domain_id": 4}]
            if sql.startswith("SELECT COUNT(*) AS count"):
                return [{"count": 2}]
            if sql.startswith("SELECT event_hash"):
                return [{"event_hash": "f" * 64}]
            if sql.startswith("INSERT IGNORE INTO decision_audit_head"):
                self.inserted.append(params or {})
            return []

    db = AuditHeadDB()
    monkeypatch.setattr(migrations, "get_management_db", lambda: db)

    await migrations.backfill_decision_audit_heads()

    assert db.inserted == [
        {"domain_id": 4, "event_count": 2, "head_hash": "f" * 64}
    ]
