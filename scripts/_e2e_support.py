"""Shared cleanup helpers for local end-to-end verification scripts."""

from __future__ import annotations

from typing import Any

from app.db.mysql import MySQLClient


async def activate_enterprise_model_release(
    client: Any,
    domain_id: int,
    headers: dict[str, str],
    ontology_release_id: int,
    *,
    name: str,
) -> dict[str, Any]:
    """Create, validate, and activate the unified release required by runtimes."""
    snapshot = await client.post(
        f"/api/semantic/domains/{domain_id}/snapshot",
        headers=headers,
        json={"name": f"{name} 语义快照", "description": "temporary e2e"},
    )
    snapshot.raise_for_status()
    draft = await client.post(
        f"/api/model-releases/domains/{domain_id}/releases",
        headers=headers,
        json={
            "semantic_snapshot_id": int(snapshot.json()["id"]),
            "ontology_release_id": int(ontology_release_id),
            "name": name,
            "description": "temporary e2e",
        },
    )
    draft.raise_for_status()
    release_id = int(draft.json()["release"]["id"])
    validation = await client.post(
        f"/api/model-releases/domains/{domain_id}/releases/{release_id}/validate",
        headers=headers,
        json={},
    )
    validation.raise_for_status()
    validated_release = validation.json()["release"]
    if validated_release["status"] != "validated":
        raise RuntimeError(
            f"enterprise model validation failed: {validated_release.get('validation')}"
        )
    activation = await client.post(
        f"/api/model-releases/domains/{domain_id}/releases/{release_id}/activate",
        headers=headers,
    )
    activation.raise_for_status()
    active_release = activation.json()["release"]
    if active_release["status"] != "active":
        raise RuntimeError(f"enterprise model activation failed: {active_release}")
    return active_release


async def delete_temporary_domain(db: MySQLClient, domain_id: int) -> None:
    """Remove one explicitly created E2E domain and all of its test records.

    Product APIs intentionally refuse to delete a governed domain after it has
    instances, releases, or audit history. Local verification scripts create
    disposable domains, so their cleanup must be explicit and stay outside the
    product API contract.
    """
    params = {"id": int(domain_id)}
    statements = [
        (f"DELETE FROM {table} WHERE domain_id = :id", params)
        for table in (
            "domain_table_permission",
            "domain_column_permission",
            "decision_audit_head",
            "decision_audit_event",
            "capability_invocation_audit",
            "capability_grant",
            "twin_sync_run",
            "risk_evidence",
            "risk_issue_review",
            "risk_report_version",
            "risk_report",
            "risk_issue",
            "ontology_action_run",
            "ontology_link",
            "ontology_object",
            "enterprise_model_release",
            "ontology_release",
            "semantic_domain_snapshot",
            "ontology_action_type",
            "ontology_link_type",
        )
    ]
    statements.extend(
        [
            (
                "DELETE p FROM ontology_property p JOIN ontology_object_type o "
                "ON o.id = p.object_type_id WHERE o.domain_id = :id",
                params,
            ),
            ("DELETE FROM ontology_object_type WHERE domain_id = :id", params),
        ]
    )
    statements.extend(
        (f"DELETE FROM {table} WHERE domain_id = :id", params)
        for table in (
            "logic_form_template",
            "semantic_mapping",
            "semantic_rule",
            "semantic_metric",
            "semantic_relation",
            "semantic_concept",
        )
    )
    statements.extend(
        [
            (
                "UPDATE agent SET semantic_domain_id = NULL "
                "WHERE semantic_domain_id = :id",
                params,
            ),
            ("DELETE FROM agent_semantic_domain WHERE domain_id = :id", params),
            ("DELETE FROM semantic_domain WHERE id = :id", params),
        ]
    )
    await db.execute_transaction(statements)
