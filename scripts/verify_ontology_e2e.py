"""Replay the complete local Ontology workflow against a running WenQu instance.

The script creates temporary database records and removes them in ``finally``. It
prints only status/counts, never credentials or access tokens.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import httpx

from app.db.migrations import run_management_migrations
from app.db.mysql import get_management_db
from app.services.user_service import hash_password

BASE_URL = "http://127.0.0.1:4400"
BUNDLE_PATH = Path(__file__).parents[1] / "examples/supply_chain/ontology-bundle.json"


async def main() -> None:
    await run_management_migrations()
    db = get_management_db()
    suffix = uuid.uuid4().hex[:8]
    username = f"ontology_e2e_{suffix}"
    password = f"OntologyE2e-{suffix}!"
    user_id = await db.execute_insert(
        "INSERT INTO app_user (username, password_hash, display_name, role, status) "
        "VALUES (:username, :password_hash, :display_name, 'admin', 'active')",
        {
            "username": username,
            "password_hash": hash_password(password),
            "display_name": "Ontology E2E",
        },
    )
    agent_rows = await db.execute_query("SELECT id FROM agent ORDER BY id LIMIT 1")
    temporary_agent_id: int | None = None
    if agent_rows:
        agent_id = int(agent_rows[0]["id"])
    else:
        temporary_agent_id = await db.execute_insert(
            "INSERT INTO agent (name, description) VALUES (:name, :description)",
            {"name": f"Ontology E2E {suffix}", "description": "temporary"},
        )
        agent_id = temporary_agent_id

    token = ""
    domain_id: int | None = None
    statuses: dict[str, int | bool] = {}
    headers: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
            login = await client.post(
                "/api/auth/login", json={"username": username, "password": password}
            )
            login.raise_for_status()
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            created = await client.post(
                "/api/semantic/domains",
                headers=headers,
                json={
                    "agent_id": agent_id,
                    "domain_key": f"ontology_e2e_{suffix}",
                    "name": "Ontology E2E",
                    "description": "temporary",
                    "status": "active",
                },
            )
            created.raise_for_status()
            domain_id = int(created.json()["id"])
            bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
            imported = await client.post(
                f"/api/ontology/domains/{domain_id}/import",
                headers=headers,
                json={"bundle": bundle, "replace": False},
            )
            imported.raise_for_status()
            statuses["import_status"] = imported.status_code
            validated = await client.post(
                f"/api/ontology/domains/{domain_id}/validate", headers=headers
            )
            validated.raise_for_status()
            statuses["valid"] = bool(validated.json()["valid"])
            published = await client.post(
                f"/api/ontology/domains/{domain_id}/publish",
                headers=headers,
                json={"description": "e2e"},
            )
            published.raise_for_status()
            statuses["release_version"] = int(published.json()["version"])
            actions = (
                await client.get(f"/api/ontology/domains/{domain_id}/action-types", headers=headers)
            ).json()["action_types"]
            objects = (
                await client.get(f"/api/ontology/domains/{domain_id}/objects", headers=headers)
            ).json()["objects"]
            action = next(item for item in actions if item["action_key"] == "reallocate_material")
            target = next(item for item in objects if item["object_type_key"] == "Material")
            executed = await client.post(
                f"/api/ontology/domains/{domain_id}/actions/{action['id']}/execute",
                headers=headers,
                json={
                    "target_object_id": target["id"],
                    "expected_version": target["version"],
                    "parameters": {"new_quantity": 1200, "new_status": "reallocated"},
                    "decision_context": {"reason": "supplier disruption"},
                },
            )
            executed.raise_for_status()
            statuses["action_status"] = executed.status_code
            runs = await client.get(
                f"/api/ontology/domains/{domain_id}/action-runs", headers=headers
            )
            runs.raise_for_status()
            statuses["audit_rows"] = len(runs.json()["runs"])
            exported = await client.get(
                f"/api/ontology/domains/{domain_id}/export", headers=headers
            )
            exported.raise_for_status()
            statuses["export_objects"] = len(exported.json().get("objects", []))
            print(json.dumps(statuses, ensure_ascii=False, sort_keys=True))
    finally:
        if domain_id and token:
            async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
                await client.delete(f"/api/semantic/domains/{domain_id}", headers=headers)
        if temporary_agent_id:
            await db.execute_query("DELETE FROM agent WHERE id = :id", {"id": temporary_agent_id})
        await db.execute_query("DELETE FROM app_user WHERE id = :id", {"id": user_id})
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
