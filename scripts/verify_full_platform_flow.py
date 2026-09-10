"""Verify the complete WenQu platform flow against the local loan datasource.

The script creates a disposable business domain and admin account, imports the
loan semantic/Ontology examples, configures domain-owned data permissions,
publishes one active enterprise-model release, runs twin synchronization, and
compares external Capability plus built-in validation-Agent results with direct
business-database baselines. All temporary management records are removed in
``finally``.
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
from app.db.mysql import close_database_clients, get_datasource_db, get_management_db
from app.services.user_service import hash_password
from scripts._e2e_support import delete_temporary_domain

BASE_URL = os.getenv("WENQU_BASE_URL", "http://127.0.0.1:4400")
ROOT = Path(__file__).parents[1]
SEMANTIC_PATH = ROOT / "examples/loan/semantic-domain.json"
ONTOLOGY_PATH = ROOT / "examples/loan/ontology-bundle.json"
DATASOURCE_ID = 1
VALIDATION_AGENT_ID = 1
CORE_TABLES = [
    "collection_case_indicator",
    "customer_risk_monthly_indicator",
    "loan_account_indicator",
    "loan_application_indicator",
    "loan_repayment_period_indicator",
]


def _semantic_import_bundle(suffix: str) -> dict[str, Any]:
    source = json.loads(SEMANTIC_PATH.read_text(encoding="utf-8"))
    domain = dict(source["domain"])
    domain.update(
        {
            "id": None,
            "agent_id": None,
            "datasource_id": DATASOURCE_ID,
            "domain_key": f"loan_platform_e2e_{suffix}",
            "name": "贷款业务全链路 E2E",
            "description": "temporary full-platform verification",
            "status": "active",
        }
    )
    assets: dict[str, list[dict[str, Any]]] = {}
    for source_key, target_key in (
        ("concepts", "concept"),
        ("relations", "relation"),
        ("metrics", "metric"),
        ("rules", "rule"),
        ("mappings", "mapping"),
        ("templates", "template"),
    ):
        assets[target_key] = []
        for raw_item in source.get(source_key) or []:
            item = dict(raw_item)
            for field in ("id", "domain_id", "created_at", "updated_at"):
                item.pop(field, None)
            assets[target_key].append(item)
    return {"domain": domain, "assets": assets}


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    expected: set[int] | None = None,
) -> tuple[int, dict[str, Any]]:
    response = await client.request(method, path, headers=headers, json=payload)
    allowed = expected or {200, 201}
    if response.status_code not in allowed:
        raise RuntimeError(
            f"{method} {path} failed with {response.status_code}: {response.text}"
        )
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"{method} {path} did not return a JSON object")
    return response.status_code, body


def _grouped(rows: list[dict[str, Any]], dimension: str) -> dict[str, int]:
    return {
        str(row[dimension]): int(row["application_count"])
        for row in rows
    }


def _assert_query_result(
    result: dict[str, Any],
    expected: int | dict[str, int],
    dimension: str | None = None,
) -> None:
    if result.get("status") != "succeeded":
        raise RuntimeError(f"query did not succeed: {result}")
    rows = (result.get("result") or {}).get("sql_result") or []
    if dimension is None:
        actual: int | dict[str, int] = int(rows[0]["application_count"])
    else:
        actual = _grouped(rows, dimension)
    if actual != expected:
        raise RuntimeError(f"query result mismatch: actual={actual}, expected={expected}")


def _assert_chat_result(
    result: dict[str, Any],
    expected: dict[str, int],
    dimension: str,
) -> None:
    logic_form = result.get("logic_form") or {}
    if logic_form.get("metrics") != ["application_count"]:
        raise RuntimeError(f"chat metric mismatch: {logic_form}")
    if logic_form.get("dimensions") != [dimension]:
        raise RuntimeError(f"chat dimension mismatch: {logic_form}")
    actual = _grouped(result.get("sql_result") or [], dimension)
    if actual != expected:
        raise RuntimeError(
            f"chat result mismatch for {dimension}: actual={actual}, expected={expected}"
        )


async def _business_baseline() -> dict[str, Any]:
    business_db = await get_datasource_db(DATASOURCE_ID)
    total = await business_db.execute_query(
        "SELECT COUNT(*) AS application_count FROM loan_application_indicator"
    )
    statuses = await business_db.execute_query(
        "SELECT approval_status AS application_approval_status, "
        "COUNT(*) AS application_count FROM loan_application_indicator "
        "GROUP BY approval_status"
    )
    channels = await business_db.execute_query(
        "SELECT channel AS application_channel, COUNT(*) AS application_count "
        "FROM loan_application_indicator GROUP BY channel"
    )
    return {
        "total": int(total[0]["application_count"]),
        "approval_status": _grouped(statuses, "application_approval_status"),
        "channel": _grouped(channels, "application_channel"),
    }


async def main() -> None:
    await run_management_migrations()
    management_db = get_management_db()
    suffix = uuid.uuid4().hex[:8]
    username = f"full_platform_e2e_{suffix}"
    password = f"FullPlatformE2e-{suffix}!"
    user_id = await management_db.execute_insert(
        "INSERT INTO app_user (username, password_hash, display_name, role, status) "
        "VALUES (:username, :password_hash, :display_name, 'admin', 'active')",
        {
            "username": username,
            "password_hash": hash_password(password),
            "display_name": "Full Platform E2E",
        },
    )
    domain_id: int | None = None
    capability_client_id: int | None = None
    session_id = f"full-platform-e2e-{suffix}"
    report: dict[str, Any] = {
        "flow": "enterprise_model_to_agent",
        "datasource_id": DATASOURCE_ID,
    }
    try:
        baseline = await _business_baseline()
        report["business_baseline"] = baseline

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=240) as client:
            _, login = await _request_json(
                client,
                "POST",
                "/api/auth/login",
                payload={"username": username, "password": password},
            )
            headers = {"Authorization": f"Bearer {login['access_token']}"}

            _, collected = await _request_json(
                client,
                "POST",
                f"/api/datasource/{DATASOURCE_ID}/collect-schema",
                headers=headers,
                payload={"table_names": CORE_TABLES},
            )
            collected_names = {
                str(item.get("table_name")) for item in collected.get("tables") or []
            }
            missing_tables = sorted(set(CORE_TABLES) - collected_names)
            if missing_tables:
                raise RuntimeError(f"schema collection missed tables: {missing_tables}")
            report["schema_tables"] = sorted(collected_names)

            _, imported_semantic = await _request_json(
                client,
                "POST",
                "/api/semantic/domains/import",
                headers=headers,
                payload=_semantic_import_bundle(suffix),
            )
            domain_id = int(imported_semantic["id"])
            report["domain_id"] = domain_id

            permission_payload = {
                "table_permissions": [
                    {"table_name": table, "allowed": True} for table in CORE_TABLES
                ],
                "column_permissions": [],
            }
            _, permissions = await _request_json(
                client,
                "PUT",
                f"/api/datasource/{DATASOURCE_ID}/domain-permissions/{domain_id}",
                headers=headers,
                payload=permission_payload,
            )
            report["permission_source"] = "domain"
            report["allowed_tables"] = sorted(
                item["table_name"]
                for item in permissions["permissions"]["table_permissions"]
                if item["allowed"]
            )

            ontology_bundle = json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))
            _, imported_ontology = await _request_json(
                client,
                "POST",
                f"/api/ontology/domains/{domain_id}/import",
                headers=headers,
                payload={"bundle": ontology_bundle, "replace": False},
            )
            report["ontology_import"] = imported_ontology["imported"]

            _, object_type_response = await _request_json(
                client,
                "GET",
                f"/api/ontology/domains/{domain_id}/object-types",
                headers=headers,
            )
            object_types = object_type_response["object_types"]
            preview_counts: dict[str, int] = {}
            for object_type in object_types:
                if not object_type.get("sync_enabled"):
                    continue
                _, preview = await _request_json(
                    client,
                    "POST",
                    f"/api/ontology/domains/{domain_id}/object-types/mapping-preview",
                    headers=headers,
                    payload=object_type,
                )
                if not preview.get("valid"):
                    raise RuntimeError(
                        f"object mapping preview invalid for {object_type['object_key']}: "
                        f"{preview.get('errors')}"
                    )
                preview_counts[str(object_type["object_key"])] = int(
                    (preview.get("statistics") or {}).get("sample_rows") or 0
                )
            if not preview_counts or any(count == 0 for count in preview_counts.values()):
                raise RuntimeError(f"object mapping preview returned no rows: {preview_counts}")
            report["mapping_preview_rows"] = preview_counts

            _, semantic_validation = await _request_json(
                client,
                "POST",
                f"/api/semantic/domains/{domain_id}/validate",
                headers=headers,
            )
            if not semantic_validation.get("valid"):
                raise RuntimeError(f"semantic validation failed: {semantic_validation}")
            _, ontology_validation = await _request_json(
                client,
                "POST",
                f"/api/ontology/domains/{domain_id}/validate",
                headers=headers,
            )
            if not ontology_validation.get("valid"):
                raise RuntimeError(f"ontology validation failed: {ontology_validation}")

            _, snapshot = await _request_json(
                client,
                "POST",
                f"/api/semantic/domains/{domain_id}/snapshot",
                headers=headers,
                payload={"name": "全链路语义快照", "description": "temporary e2e"},
            )
            _, ontology_release = await _request_json(
                client,
                "POST",
                f"/api/ontology/domains/{domain_id}/publish",
                headers=headers,
                payload={"name": "全链路 Ontology V1", "description": "temporary e2e"},
            )
            _, draft = await _request_json(
                client,
                "POST",
                f"/api/model-releases/domains/{domain_id}/releases",
                headers=headers,
                payload={
                    "semantic_snapshot_id": int(snapshot["id"]),
                    "ontology_release_id": int(ontology_release["id"]),
                    "name": "全链路企业模型 V1",
                    "description": "temporary e2e",
                },
            )
            model_release_id = int(draft["release"]["id"])
            _, validated = await _request_json(
                client,
                "POST",
                f"/api/model-releases/domains/{domain_id}/releases/"
                f"{model_release_id}/validate",
                headers=headers,
                payload={},
            )
            if validated["release"]["status"] != "validated":
                raise RuntimeError(
                    f"enterprise model validation failed: {validated['release']['validation']}"
                )
            _, activated = await _request_json(
                client,
                "POST",
                f"/api/model-releases/domains/{domain_id}/releases/"
                f"{model_release_id}/activate",
                headers=headers,
            )
            if activated["release"]["status"] != "active":
                raise RuntimeError(f"enterprise model activation failed: {activated}")
            report["model_release"] = {
                "id": model_release_id,
                "status": "active",
                "semantic_snapshot_id": int(snapshot["id"]),
                "ontology_release_id": int(ontology_release["id"]),
            }

            loan_application_type = next(
                item for item in object_types if item["object_key"] == "LoanApplication"
            )
            _, dry_run = await _request_json(
                client,
                "POST",
                f"/api/twin/domains/{domain_id}/sync-runs",
                headers=headers,
                payload={
                    "object_type_id": int(loan_application_type["id"]),
                    "page": 1,
                    "page_size": 20,
                    "sync_links": True,
                    "dry_run": True,
                },
            )
            if dry_run["run"]["status"] not in {"succeeded", "partial"}:
                raise RuntimeError(f"twin dry-run failed: {dry_run}")
            _, synced = await _request_json(
                client,
                "POST",
                f"/api/twin/domains/{domain_id}/sync-runs",
                headers=headers,
                payload={
                    "page": 1,
                    "page_size": 20,
                    "sync_links": True,
                    "dry_run": False,
                },
            )
            if synced["run"]["status"] not in {"succeeded", "partial"}:
                raise RuntimeError(f"twin synchronization failed: {synced}")
            masked_permission_payload = {
                **permission_payload,
                "column_permissions": [
                    {
                        "table_name": "loan_application_indicator",
                        "column_name": "reject_reason",
                        "allowed": False,
                        "masking_policy": "redact",
                    }
                ],
            }
            await _request_json(
                client,
                "PUT",
                f"/api/datasource/{DATASOURCE_ID}/domain-permissions/{domain_id}",
                headers=headers,
                payload=masked_permission_payload,
            )
            _, runtime_objects = await _request_json(
                client,
                "GET",
                f"/api/ontology/domains/{domain_id}/objects?strict_release=true&limit=1000",
                headers=headers,
            )
            database_objects = [
                item
                for item in runtime_objects.get("objects") or []
                if item.get("source_kind") == "database"
            ]
            if not database_objects:
                raise RuntimeError("twin synchronization created no database-backed objects")
            leaked_reject_reason = any(
                "decision_note" in (item.get("properties") or {})
                for item in database_objects
                if item.get("object_type_key") == "LoanApplication"
            )
            if leaked_reject_reason:
                raise RuntimeError("denied reject_reason leaked through object properties")
            _, runtime_links = await _request_json(
                client,
                "GET",
                f"/api/ontology/domains/{domain_id}/links?strict_release=true",
                headers=headers,
            )
            report["twin_runtime"] = {
                "dry_run_status": dry_run["run"]["status"],
                "sync_status": synced["run"]["status"],
                "database_objects": len(database_objects),
                "links": len(runtime_links.get("links") or []),
                "model_release_id": synced["run"].get("model_release_id"),
            }
            if int(synced["run"].get("model_release_id") or 0) != model_release_id:
                raise RuntimeError("twin run is not bound to the active model release")

            _, capability_list = await _request_json(
                client,
                "GET",
                f"/api/ontology/domains/{domain_id}/query-capabilities",
                headers=headers,
            )
            capabilities = {
                item["key"]: item for item in capability_list["query_capabilities"]
            }
            application_capability = capabilities.get("query_loan_application")
            if not application_capability:
                raise RuntimeError(f"loan application capability missing: {capabilities}")
            required_dimensions = {
                "application_approval_status",
                "application_channel",
            }
            if "application_count" not in application_capability["supported_metrics"] or not (
                required_dimensions
                <= set(application_capability["supported_dimensions"])
            ):
                raise RuntimeError(
                    f"loan application capability contract incomplete: {application_capability}"
                )

            _, created_client = await _request_json(
                client,
                "POST",
                "/api/capability-clients",
                headers=headers,
                payload={"name": "全链路外部 Agent", "description": "temporary e2e"},
            )
            credential = created_client["credential"]
            capability_client_id = int(credential["client"]["id"])
            external_headers = {
                "X-Capability-Key": credential["client_key"],
                "X-Capability-Secret": credential["client_secret"],
            }
            _, application_grant = await _request_json(
                client,
                "PUT",
                f"/api/capability-clients/{capability_client_id}/grants",
                headers=headers,
                payload={
                    "domain_id": domain_id,
                    "capability_key": "query_loan_application",
                    "status": "active",
                },
            )
            if application_grant["grant"].get("execution_agent_id") is not None:
                raise RuntimeError("domain-owned capability grant unexpectedly depends on an Agent")

            async def invoke_application(dimensions: list[str]) -> dict[str, Any]:
                _, response = await _request_json(
                    client,
                    "POST",
                    "/api/v1/capabilities/query_loan_application:invoke",
                    headers=external_headers,
                    payload={
                        "domain_id": domain_id,
                        "model_release_id": model_release_id,
                        "logic_form": {
                            "intent_type": "metric_query",
                            "metrics": ["application_count"],
                            "dimensions": dimensions,
                        },
                    },
                )
                serialized = json.dumps(response, ensure_ascii=False).lower()
                if "compiled_sql" in serialized or "executed_sql" in serialized:
                    raise RuntimeError("external capability response leaked physical SQL")
                return response

            total_result = await invoke_application([])
            status_result = await invoke_application(["application_approval_status"])
            channel_result = await invoke_application(["application_channel"])
            _assert_query_result(total_result, baseline["total"])
            _assert_query_result(
                status_result,
                baseline["approval_status"],
                "application_approval_status",
            )
            _assert_query_result(
                channel_result,
                baseline["channel"],
                "application_channel",
            )
            report["external_query"] = {
                "total": baseline["total"],
                "approval_status_groups": len(baseline["approval_status"]),
                "channel_groups": len(baseline["channel"]),
                "release_id": model_release_id,
                "agent_independent": True,
            }

            account_capability = capabilities.get("query_loan_account")
            if not account_capability:
                raise RuntimeError("loan account capability missing for permission test")
            await _request_json(
                client,
                "PUT",
                f"/api/capability-clients/{capability_client_id}/grants",
                headers=headers,
                payload={
                    "domain_id": domain_id,
                    "capability_key": "query_loan_account",
                    "status": "active",
                },
            )
            await _request_json(
                client,
                "PUT",
                f"/api/datasource/{DATASOURCE_ID}/domain-permissions/{domain_id}",
                headers=headers,
                payload={
                    "table_permissions": [
                        {"table_name": "loan_application_indicator", "allowed": True}
                    ],
                    "column_permissions": [],
                },
            )
            denied_status, denied = await _request_json(
                client,
                "POST",
                "/api/v1/capabilities/query_loan_account:invoke",
                headers=external_headers,
                payload={
                    "domain_id": domain_id,
                    "model_release_id": model_release_id,
                    "logic_form": {
                        "intent_type": "metric_query",
                        "metrics": ["outstanding_balance"],
                    },
                },
                expected={200, 403},
            )
            denied_result_status = (
                denied.get("status")
                if denied_status == 200
                else "permission_blocked"
            )
            if denied_result_status != "permission_blocked":
                raise RuntimeError(f"table allowlist did not block loan account query: {denied}")
            report["permission_block"] = "loan_account_indicator"
            await _request_json(
                client,
                "PUT",
                f"/api/datasource/{DATASOURCE_ID}/domain-permissions/{domain_id}",
                headers=headers,
                payload=permission_payload,
            )

            _, chat_status = await _request_json(
                client,
                "POST",
                "/api/chat",
                headers=headers,
                payload={
                    "question": "查看审批进度，按申请状态统计当前贷款申请数量。",
                    "agent_id": VALIDATION_AGENT_ID,
                    "domain_id": domain_id,
                    "model_release_id": model_release_id,
                    "session_id": session_id,
                    "turn_mode": "new_task",
                },
            )
            _assert_chat_result(
                chat_status,
                baseline["approval_status"],
                "application_approval_status",
            )
            _, chat_channel = await _request_json(
                client,
                "POST",
                "/api/chat",
                headers=headers,
                payload={
                    "question": "按申请渠道统计",
                    "agent_id": VALIDATION_AGENT_ID,
                    "domain_id": domain_id,
                    "model_release_id": model_release_id,
                    "session_id": session_id,
                    "turn_mode": "refine",
                },
            )
            _assert_chat_result(
                chat_channel,
                baseline["channel"],
                "application_channel",
            )
            report["validation_agent"] = {
                "status_question": "matched",
                "followup_channel_question": "matched",
                "same_session": True,
                "model_release_id": model_release_id,
            }

            _, audits = await _request_json(
                client,
                "GET",
                f"/api/capability-invocations?client_id={capability_client_id}"
                f"&domain_id={domain_id}&limit=20",
                headers=headers,
            )
            succeeded_audits = [
                item
                for item in audits.get("invocations") or []
                if item.get("status") == "succeeded"
            ]
            if len(succeeded_audits) < 3 or any(
                int(item.get("model_release_id") or 0) != model_release_id
                for item in succeeded_audits
            ):
                raise RuntimeError(f"capability audit lineage mismatch: {audits}")
            report["capability_audits"] = len(audits.get("invocations") or [])

        report["status"] = "passed"
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    finally:
        if domain_id is not None:
            await delete_temporary_domain(management_db, domain_id)
        if capability_client_id is not None:
            await management_db.execute_query(
                "DELETE FROM capability_client WHERE id = :id",
                {"id": capability_client_id},
            )
        await management_db.execute_transaction(
            [
                ("DELETE FROM chat_history WHERE user_id = :id", {"id": user_id}),
                ("DELETE FROM agent_task_checkpoint WHERE user_id = :id", {"id": user_id}),
                ("DELETE FROM user_feedback WHERE user_id = :id", {"id": user_id}),
                ("DELETE FROM app_user WHERE id = :id", {"id": user_id}),
            ]
        )
        await close_database_clients()


if __name__ == "__main__":
    asyncio.run(main())
