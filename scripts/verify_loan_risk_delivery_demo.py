"""Replay the loan risk-delivery demo against a running local WenQu instance.

The script creates a temporary admin and domain, imports and publishes the loan
Ontology, executes the risk workflow bundle, verifies the audit hash chain, and
removes temporary records in ``finally``.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.db.migrations import run_management_migrations
from app.db.mysql import get_management_db
from app.services.user_service import hash_password

BASE_URL = os.getenv("WENQU_BASE_URL", "http://127.0.0.1:4400")
ROOT = Path(__file__).parents[1]
ONTOLOGY_BUNDLE_PATH = ROOT / "examples/loan/ontology-bundle.json"
RISK_BUNDLE_PATH = ROOT / "examples/loan/risk-workflow-bundle.json"


def _created_id(payload: dict[str, Any], entity: str) -> int:
    for key in ("id", f"{entity}_id"):
        value = payload.get(key)
        if value is not None:
            return int(value)
    nested = payload.get(entity)
    if isinstance(nested, dict) and nested.get("id") is not None:
        return int(nested["id"])
    raise RuntimeError(f"{entity} create response missing id: {payload}")


def _audit_events(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("events", "audit_events", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise RuntimeError(f"audit response missing event list: {payload}")


def _audit_chain_valid(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("valid", "chain_valid", "verified"):
        if key in payload:
            return payload[key] is True
    result = payload.get("result")
    return isinstance(result, dict) and _audit_chain_valid(result)


async def _post_json(
    client: httpx.AsyncClient,
    path: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post(path, headers=headers, json=payload)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"expected JSON object from {path}")
    return body


def _version_payload(spec: dict[str, Any], issue_ids: list[int]) -> dict[str, Any]:
    payload = dict(spec["request"])
    payload["issue_ids"] = issue_ids
    return payload


async def main() -> None:
    await run_management_migrations()
    db = get_management_db()
    suffix = uuid.uuid4().hex[:8]
    username = f"loan_risk_delivery_e2e_{suffix}"
    password = f"LoanRiskDeliveryE2e-{suffix}!"
    user_id = await db.execute_insert(
        "INSERT INTO app_user (username, password_hash, display_name, role, status) "
        "VALUES (:username, :password_hash, :display_name, 'admin', 'active')",
        {
            "username": username,
            "password_hash": hash_password(password),
            "display_name": "Loan Risk Delivery E2E",
        },
    )
    agent_rows = await db.execute_query("SELECT id FROM agent ORDER BY id LIMIT 1")
    temporary_agent_id: int | None = None
    if agent_rows:
        agent_id = int(agent_rows[0]["id"])
    else:
        temporary_agent_id = await db.execute_insert(
            "INSERT INTO agent (name, description) VALUES (:name, :description)",
            {"name": f"Loan Risk Delivery E2E {suffix}", "description": "temporary"},
        )
        agent_id = temporary_agent_id

    token = ""
    domain_id: int | None = None
    headers: dict[str, str] = {}
    statuses: dict[str, int | bool] = {}
    try:
        ontology_bundle = json.loads(ONTOLOGY_BUNDLE_PATH.read_text(encoding="utf-8"))
        risk_bundle = json.loads(RISK_BUNDLE_PATH.read_text(encoding="utf-8"))
        if risk_bundle.get("format") != "wenqu-risk-workflow":
            raise RuntimeError("unsupported loan risk workflow bundle")

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
            login = await client.post(
                "/api/auth/login", json={"username": username, "password": password}
            )
            login.raise_for_status()
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            created = await _post_json(
                client,
                "/api/semantic/domains",
                headers,
                {
                    "agent_id": agent_id,
                    "domain_key": f"loan_risk_delivery_e2e_{suffix}",
                    "name": "贷款风险交付 E2E",
                    "description": "temporary",
                    "status": "active",
                },
            )
            domain_id = int(created["id"])

            imported = await client.post(
                f"/api/ontology/domains/{domain_id}/import",
                headers=headers,
                json={"bundle": ontology_bundle, "replace": False},
            )
            imported.raise_for_status()
            statuses["ontology_import_status"] = imported.status_code

            validated = await client.post(
                f"/api/ontology/domains/{domain_id}/validate", headers=headers
            )
            validated.raise_for_status()
            validation = validated.json()
            if not validation["valid"]:
                raise RuntimeError(f"loan Ontology bundle invalid: {validation}")
            statuses["ontology_valid"] = True

            release_spec = risk_bundle["ontology"]
            published = await _post_json(
                client,
                f"/api/ontology/domains/{domain_id}/publish",
                headers,
                {
                    "name": release_spec["release_name"],
                    "description": release_spec["release_description"],
                },
            )
            ontology_release_id = int(published["id"])
            statuses["ontology_release_version"] = int(published["version"])

            object_response = await client.get(
                f"/api/ontology/domains/{domain_id}/objects", headers=headers
            )
            object_response.raise_for_status()
            objects = {
                (item["object_type_key"], str(item["primary_value"])): item
                for item in object_response.json()["objects"]
            }

            issue_ids: dict[str, int] = {}
            issue_versions: dict[str, int] = {}
            evidence_count = 0
            for issue_spec in risk_bundle["issues"]:
                subject = issue_spec["subject"]
                object_key = (subject["object_type_key"], str(subject["primary_value"]))
                target = objects.get(object_key)
                if target is None:
                    raise RuntimeError(f"risk subject Ontology object not found: {object_key}")

                issue_payload = dict(issue_spec["request"])
                source_context = dict(issue_payload["source_context"])
                if source_context["display_name"] != target["display_name"]:
                    raise RuntimeError(f"risk subject display name mismatch: {object_key}")
                source_context["ontology_object_id"] = int(target["id"])
                issue_payload["source_context"] = source_context
                issue_payload["domain_id"] = domain_id
                issue_payload["subject_object_id"] = int(target["id"])
                issue = await _post_json(
                    client,
                    f"/api/risk/domains/{domain_id}/issues",
                    headers,
                    issue_payload,
                )
                issue_id = _created_id(issue, "issue")
                issue_ids[issue_spec["ref"]] = issue_id
                issue_versions[issue_spec["ref"]] = int(issue["version"])

                for evidence_spec in issue_spec["evidence"]:
                    await _post_json(
                        client,
                        f"/api/risk/domains/{domain_id}/issues/{issue_id}/evidence",
                        headers,
                        evidence_spec["request"],
                    )
                    evidence_count += 1

            report_spec = risk_bundle["report"]
            report_issue_ids = [issue_ids[ref] for ref in report_spec["issue_refs"]]
            version_specs = {item["ref"]: item for item in report_spec["versions"]}
            report_payload = {
                **report_spec["request"],
                **_version_payload(version_specs["V1"], report_issue_ids),
                "domain_id": domain_id,
            }
            report = await _post_json(
                client,
                f"/api/risk/domains/{domain_id}/reports",
                headers,
                report_payload,
            )
            report_id = _created_id(report, "report")
            v1 = report["version"]
            if int(v1["version"]) != 1:
                raise RuntimeError(f"report create did not return V1: {v1}")
            if int(v1["ontology_release_id"]) != ontology_release_id:
                raise RuntimeError("report V1 is not bound to the published Ontology release")
            version_ids: dict[str, int] = {"V1": int(v1["id"])}

            review_count = 0
            for issue_spec in risk_bundle["issues"]:
                issue_id = issue_ids[issue_spec["ref"]]
                await _post_json(
                    client,
                    f"/api/risk/domains/{domain_id}/issues/{issue_id}/reviews",
                    headers,
                    {
                        **issue_spec["review"]["request"],
                        "expected_version": issue_versions[issue_spec["ref"]],
                    },
                )
                review_count += 1

            v2 = await _post_json(
                client,
                f"/api/risk/domains/{domain_id}/reports/{report_id}/versions",
                headers,
                {
                    **_version_payload(version_specs["V2"], report_issue_ids),
                    "expected_current_version": 1,
                },
            )
            if int(v2["version"]) != 2:
                raise RuntimeError(f"report version endpoint did not return V2: {v2}")
            if int(v2["ontology_release_id"]) != ontology_release_id:
                raise RuntimeError("report V2 is not bound to the published Ontology release")
            version_ids["V2"] = _created_id(v2, "version")

            finalize_ref = report_spec["finalize"]["version_ref"]
            if finalize_ref != "V2":
                raise RuntimeError(f"unsupported finalize version: {finalize_ref}")
            finalized = await client.post(
                f"/api/risk/domains/{domain_id}/reports/{report_id}/finalize",
                headers=headers,
                json={"expected_version": 2},
            )
            finalized.raise_for_status()

            audit_response = await client.get(
                f"/api/risk/domains/{domain_id}/audit", headers=headers
            )
            audit_response.raise_for_status()
            events = _audit_events(audit_response.json())
            expected_events = int(risk_bundle["expected_audit_events"])
            if len(events) < expected_events:
                raise RuntimeError(
                    f"expected at least {expected_events} audit events, got {len(events)}"
                )

            verify_response = await client.get(
                f"/api/risk/domains/{domain_id}/audit/verify", headers=headers
            )
            verify_response.raise_for_status()
            chain_valid = _audit_chain_valid(verify_response.json())
            if not chain_valid:
                raise RuntimeError(f"risk audit hash chain invalid: {verify_response.json()}")

            statuses.update(
                {
                    "risk_issue_count": len(issue_ids),
                    "evidence_count": evidence_count,
                    "review_count": review_count,
                    "report_version_count": len(version_ids),
                    "report_finalized": True,
                    "audit_event_count": len(events),
                    "audit_chain_valid": chain_valid,
                }
            )
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
