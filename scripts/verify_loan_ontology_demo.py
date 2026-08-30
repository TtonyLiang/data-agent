"""Replay the loan Ontology demo against a running local WenQu instance.

The script creates a temporary admin, domain, and Ontology release, runs the
approval, collection, and case-closing actions, prints only counts/statuses,
and removes all temporary records in ``finally``.
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
BUNDLE_PATH = Path(__file__).parents[1] / "examples/loan/ontology-bundle.json"


async def main() -> None:
    await run_management_migrations()
    db = get_management_db()
    suffix = uuid.uuid4().hex[:8]
    username = f"loan_ontology_e2e_{suffix}"
    password = f"LoanOntologyE2e-{suffix}!"
    user_id = await db.execute_insert(
        "INSERT INTO app_user (username, password_hash, display_name, role, status) "
        "VALUES (:username, :password_hash, :display_name, 'admin', 'active')",
        {
            "username": username,
            "password_hash": hash_password(password),
            "display_name": "Loan Ontology E2E",
        },
    )
    agent_rows = await db.execute_query("SELECT id FROM agent ORDER BY id LIMIT 1")
    temporary_agent_id: int | None = None
    if agent_rows:
        agent_id = int(agent_rows[0]["id"])
    else:
        temporary_agent_id = await db.execute_insert(
            "INSERT INTO agent (name, description) VALUES (:name, :description)",
            {"name": f"Loan Ontology E2E {suffix}", "description": "temporary"},
        )
        agent_id = temporary_agent_id

    token = ""
    domain_id: int | None = None
    headers: dict[str, str] = {}
    statuses: dict[str, int | bool] = {}
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
                    "domain_key": f"loan_ontology_e2e_{suffix}",
                    "name": "贷款风控 Ontology E2E",
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
            validation = validated.json()
            statuses["valid"] = bool(validation["valid"])
            if not validation["valid"]:
                raise RuntimeError(f"loan Ontology bundle invalid: {validation}")

            published = await client.post(
                f"/api/ontology/domains/{domain_id}/publish",
                headers=headers,
                json={"name": "贷款风控 Demo V1", "description": "temporary e2e"},
            )
            published.raise_for_status()
            statuses["release_version"] = int(published.json()["version"])

            action_items = (
                await client.get(
                    f"/api/ontology/domains/{domain_id}/action-types", headers=headers
                )
            ).json()["action_types"]
            object_items = (
                await client.get(f"/api/ontology/domains/{domain_id}/objects", headers=headers)
            ).json()["objects"]
            actions = {item["action_key"]: item for item in action_items}
            objects = {
                (item["object_type_key"], str(item["primary_value"])): item
                for item in object_items
            }

            application = objects[("LoanApplication", "900001")]
            approved = await client.post(
                f"/api/ontology/domains/{domain_id}/actions/"
                f"{actions['approve_application']['id']}/execute",
                headers=headers,
                json={
                    "target_object_id": application["id"],
                    "expected_version": application["version"],
                    "parameters": {
                        "approved_amount": 50000,
                        "decision_note": "风险等级C，黑名单未命中，人工复核通过",
                    },
                    "approval_reference": "APR-20260830-0001",
                    "decision_context": {"source": "loan Ontology demo"},
                },
            )
            approved.raise_for_status()
            statuses["approval_status"] = approved.status_code

            account = objects[("LoanAccount", "700001")]
            collected = await client.post(
                f"/api/ontology/domains/{domain_id}/actions/"
                f"{actions['start_collection']['id']}/execute",
                headers=headers,
                json={
                    "target_object_id": account["id"],
                    "expected_version": account["version"],
                    "parameters": {
                        "collection_strategy": "电话催收",
                        "reason": "当前逾期45天，属于M1+，未核销",
                    },
                    "decision_context": {"customer_id": 200001, "source": "loan Ontology demo"},
                },
            )
            collected.raise_for_status()
            statuses["collection_status"] = collected.status_code

            case = objects[("CollectionCase", "500001")]
            closed = await client.post(
                f"/api/ontology/domains/{domain_id}/actions/"
                f"{actions['close_collection_case']['id']}/execute",
                headers=headers,
                json={
                    "target_object_id": case["id"],
                    "expected_version": case["version"],
                    "parameters": {
                        "recovered_principal": 12000,
                        "close_reason": "客户承诺还款并完成首笔回收",
                    },
                    "decision_context": {"source": "loan Ontology demo"},
                },
            )
            closed.raise_for_status()
            statuses["close_case_status"] = closed.status_code

            queried = await client.get(
                f"/api/ontology/domains/{domain_id}/query",
                headers=headers,
                params={"object_type_key": "LoanAccount", "search": "LN-20250001"},
            )
            queried.raise_for_status()
            statuses["query_rows"] = len(queried.json()["objects"])

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
            statuses["export_links"] = len(exported.json().get("links", []))
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
