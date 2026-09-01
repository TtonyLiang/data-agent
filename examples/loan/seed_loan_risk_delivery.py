"""Seed persistent loan risk-delivery demo issues from existing Ontology objects."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.db.mysql import get_management_db
from app.models.risk_workflow import (
    EvidenceCreatePayload,
    RiskIssueCreatePayload,
    RiskReviewPayload,
)
from app.services.risk_workflow_service import (
    get_risk_workflow_service,
    review_target_status,
)

DOMAIN_KEY = "loan_risk"
ACTOR_USERNAME = "wenqu_demo_admin"
POLICY_STATUS = "technical_demo_only"
M1_OVERDUE_DAYS_THRESHOLD = 30
HIGH_DTI_THRESHOLD = 0.60

LOAN_ACCOUNT_KEY = ("LoanAccount", "700001")
RISK_SNAPSHOT_KEY = ("CustomerRiskSnapshot", "600001")
REQUIRED_OBJECT_KEYS = (LOAN_ACCOUNT_KEY, RISK_SNAPSHOT_KEY)


@dataclass(frozen=True)
class IssuePlan:
    issue: RiskIssueCreatePayload
    evidence: tuple[EvidenceCreatePayload, ...]
    review: RiskReviewPayload
    target_status: str


@dataclass(frozen=True)
class SeedContext:
    domain_id: int
    release: dict[str, Any]
    actor: dict[str, Any]
    objects: dict[tuple[str, str], dict[str, Any]]
    existing_issues: dict[str, dict[str, Any]]


def _json_object(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{label} 不是有效 JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} 必须是 JSON 对象")
    return dict(value)


def _required_property(
    properties: dict[str, Any], key: str, object_label: str
) -> Any:
    value = properties.get(key)
    if value is None or value == "":
        raise RuntimeError(f"Ontology 对象 {object_label} 缺少属性 {key}")
    return value


def _number(value: Any, label: str) -> int | float:
    if isinstance(value, bool):
        raise RuntimeError(f"{label} 必须是数值")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RuntimeError(f"{label} 必须是数值") from exc
    if not number.is_finite():
        raise RuntimeError(f"{label} 必须是有限数值")
    return int(number) if number == number.to_integral_value() else float(number)


def _integer(value: Any, label: str) -> int:
    number = _number(value, label)
    if isinstance(number, float):
        raise RuntimeError(f"{label} 必须是整数")
    return number


def _boolean(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, "0"):
        return False
    if value in (1, "1"):
        return True
    raise RuntimeError(f"{label} 必须是布尔值")


def _object_properties(record: dict[str, Any]) -> dict[str, Any]:
    object_label = f"{record.get('object_type_key')}/{record.get('primary_value')}"
    return _json_object(record.get("properties"), f"{object_label}.properties")


def _loan_account_plan(
    domain_id: int, record: dict[str, Any], assignee: str
) -> IssuePlan:
    properties = _object_properties(record)
    object_label = f"LoanAccount/{record['primary_value']}"
    loan_id = _integer(_required_property(properties, "loan_id", object_label), "loan_id")
    overdue_days = _integer(
        _required_property(properties, "current_overdue_days", object_label),
        "current_overdue_days",
    )
    remaining_principal = _number(
        _required_property(properties, "remaining_principal", object_label),
        "remaining_principal",
    )
    is_written_off = _boolean(
        _required_property(properties, "is_written_off", object_label),
        "is_written_off",
    )
    if overdue_days <= M1_OVERDUE_DAYS_THRESHOLD or is_written_off:
        raise RuntimeError(
            f"{object_label} 不再满足技术演示条件: 逾期天数需大于 "
            f"{M1_OVERDUE_DAYS_THRESHOLD} 且未核销"
        )

    primary_value = str(record["primary_value"])
    issue = RiskIssueCreatePayload(
        domain_id=domain_id,
        subject_object_id=int(record["id"]),
        issue_key="demo_m1_collection_700001",
        category="collection_risk",
        severity="critical",
        title="M1+ 逾期催收风险（技术演示）",
        description=(
            f"贷款 {record['display_name']} 当前逾期 {overdue_days} 天，"
            f"剩余本金 {remaining_principal}，进入人工复核。"
        ),
        rule_key="demo_m1_collection_technical",
        detected_value={
            "current_overdue_days": overdue_days,
            "remaining_principal": remaining_principal,
            "is_written_off": is_written_off,
        },
        expected_value={
            "current_overdue_days_lte": M1_OVERDUE_DAYS_THRESHOLD,
            "policy_status": POLICY_STATUS,
        },
        source_context={
            "seed": "seed_loan_risk_delivery.py",
            "policy_status": POLICY_STATUS,
            "object_type_key": "LoanAccount",
            "ontology_object_id": int(record["id"]),
            "primary_value": primary_value,
            "display_name": record["display_name"],
        },
        assignee=assignee,
    )
    evidence = (
        EvidenceCreatePayload(
            evidence_type="ontology_object",
            title="贷款账户 Ontology 对象快照",
            description="创建风险事项时冻结的贷款账户对象属性。",
            source_ref=f"ontology://LoanAccount/{primary_value}",
            trace_id="seed-loan-risk-m1-700001-object",
            content={
                "policy_status": POLICY_STATUS,
                "object_id": int(record["id"]),
                "object_type_key": "LoanAccount",
                "primary_value": primary_value,
                "display_name": record["display_name"],
                "properties": properties,
            },
        ),
        EvidenceCreatePayload(
            evidence_type="query",
            title="M1+ 贷款查询结果",
            description="由已同步 Ontology 对象属性构造；播种脚本不访问业务数据库。",
            source_ref=f"query://loan-risk-demo/loan-account/{primary_value}",
            trace_id="seed-loan-risk-m1-700001-query",
            content={
                "execution_mode": "derived_from_ontology_object",
                "question": f"核验贷款 {record['display_name']} 的逾期和剩余本金",
                "sql": (
                    "SELECT loan_id, loan_no, current_status, remaining_principal, "
                    "current_overdue_days, overdue_bucket, is_written_off "
                    "FROM loan_account_indicator WHERE loan_id = :loan_id"
                ),
                "parameters": {"loan_id": loan_id},
                "row_count": 1,
                "row": {
                    "loan_id": loan_id,
                    "loan_no": properties.get("loan_no"),
                    "current_status": properties.get("current_status"),
                    "remaining_principal": remaining_principal,
                    "current_overdue_days": overdue_days,
                    "overdue_bucket": properties.get("overdue_bucket"),
                    "is_written_off": is_written_off,
                },
            },
        ),
        EvidenceCreatePayload(
            evidence_type="metric",
            title="M1+ 逾期风险指标",
            description="阈值仅用于技术演示，不代表真实催收或信贷政策。",
            source_ref=f"metric://loan-risk-demo/m1/{primary_value}",
            trace_id="seed-loan-risk-m1-700001-metric",
            content={
                "policy_status": POLICY_STATUS,
                "rule_key": "demo_m1_collection_technical",
                "threshold": {
                    "metric": "current_overdue_days",
                    "operator": ">",
                    "value": M1_OVERDUE_DAYS_THRESHOLD,
                },
                "metrics": [
                    {
                        "metric_key": "current_overdue_days",
                        "value": overdue_days,
                        "unit": "day",
                    },
                    {
                        "metric_key": "remaining_principal",
                        "value": remaining_principal,
                        "unit": "CNY",
                    },
                ],
                "matched": True,
            },
        ),
    )
    review = RiskReviewPayload(
        action="start_review",
        comment="技术演示事项已进入人工复核；不代表已作出真实催收决策。",
    )
    return IssuePlan(
        issue=issue,
        evidence=evidence,
        review=review,
        target_status=review_target_status("open", review.action),
    )


def _risk_snapshot_plan(
    domain_id: int, record: dict[str, Any], assignee: str
) -> IssuePlan:
    properties = _object_properties(record)
    object_label = f"CustomerRiskSnapshot/{record['primary_value']}"
    snapshot_id = _integer(
        _required_property(properties, "snapshot_id", object_label), "snapshot_id"
    )
    customer_id = _integer(
        _required_property(properties, "customer_id", object_label), "customer_id"
    )
    dti = _number(_required_property(properties, "dti", object_label), "dti")
    if dti < HIGH_DTI_THRESHOLD:
        raise RuntimeError(
            f"{object_label} 不再满足技术演示条件: DTI 需大于等于 {HIGH_DTI_THRESHOLD}"
        )

    primary_value = str(record["primary_value"])
    issue = RiskIssueCreatePayload(
        domain_id=domain_id,
        subject_object_id=int(record["id"]),
        issue_key="demo_high_dti_600001",
        category="credit_risk",
        severity="high",
        title="高 DTI 补充资料风险（技术演示）",
        description=(
            f"客户风险快照 {record['display_name']} 的 DTI 为 {dti}，"
            "需补充收入和负债资料后再复核。"
        ),
        rule_key="demo_high_dti_technical",
        detected_value={
            "dti": dti,
            "risk_grade": properties.get("risk_grade"),
            "model_pd": properties.get("model_pd"),
        },
        expected_value={
            "dti_lt": HIGH_DTI_THRESHOLD,
            "policy_status": POLICY_STATUS,
        },
        source_context={
            "seed": "seed_loan_risk_delivery.py",
            "policy_status": POLICY_STATUS,
            "object_type_key": "CustomerRiskSnapshot",
            "ontology_object_id": int(record["id"]),
            "primary_value": primary_value,
            "display_name": record["display_name"],
            "customer_id": customer_id,
            "stat_month": properties.get("stat_month"),
        },
        assignee=assignee,
    )
    evidence = (
        EvidenceCreatePayload(
            evidence_type="ontology_object",
            title="客户风险快照 Ontology 对象证据",
            description="创建风险事项时冻结的客户风险快照属性。",
            source_ref=f"ontology://CustomerRiskSnapshot/{primary_value}",
            trace_id="seed-loan-risk-dti-600001-object",
            content={
                "policy_status": POLICY_STATUS,
                "object_id": int(record["id"]),
                "object_type_key": "CustomerRiskSnapshot",
                "primary_value": primary_value,
                "display_name": record["display_name"],
                "properties": properties,
            },
        ),
        EvidenceCreatePayload(
            evidence_type="query",
            title="客户风险快照查询结果",
            description="由已同步 Ontology 对象属性构造；播种脚本不访问业务数据库。",
            source_ref=f"query://loan-risk-demo/customer-risk/{primary_value}",
            trace_id="seed-loan-risk-dti-600001-query",
            content={
                "execution_mode": "derived_from_ontology_object",
                "question": f"核验客户 {customer_id} 的 DTI 与风险等级",
                "sql": (
                    "SELECT snapshot_id, customer_id, stat_month, dti, max_dpd_12m, "
                    "risk_grade, model_pd FROM customer_risk_monthly_indicator "
                    "WHERE snapshot_id = :snapshot_id"
                ),
                "parameters": {"snapshot_id": snapshot_id},
                "row_count": 1,
                "row": {
                    "snapshot_id": snapshot_id,
                    "customer_id": customer_id,
                    "stat_month": properties.get("stat_month"),
                    "dti": dti,
                    "max_dpd_12m": properties.get("max_dpd_12m"),
                    "risk_grade": properties.get("risk_grade"),
                    "model_pd": properties.get("model_pd"),
                },
            },
        ),
        EvidenceCreatePayload(
            evidence_type="metric",
            title="客户负债收入比指标",
            description="阈值仅用于技术演示，不代表真实授信政策。",
            source_ref=f"metric://loan-risk-demo/dti/{primary_value}",
            trace_id="seed-loan-risk-dti-600001-metric",
            content={
                "policy_status": POLICY_STATUS,
                "rule_key": "demo_high_dti_technical",
                "metric_key": "customer_dti",
                "value": dti,
                "unit": "ratio",
                "threshold": {
                    "operator": ">=",
                    "value": HIGH_DTI_THRESHOLD,
                },
                "matched": True,
            },
        ),
    )
    review = RiskReviewPayload(
        action="request_info",
        comment=(
            "技术演示：请补充最新收入证明和外部负债明细；"
            "当前事项不形成真实授信结论。"
        ),
    )
    return IssuePlan(
        issue=issue,
        evidence=evidence,
        review=review,
        target_status=review_target_status("open", review.action),
    )


def build_issue_plans(
    domain_id: int,
    objects: dict[tuple[str, str], dict[str, Any]],
    *,
    assignee: str = ACTOR_USERNAME,
) -> tuple[IssuePlan, ...]:
    missing = [
        f"{object_type}/{primary_value}"
        for object_type, primary_value in REQUIRED_OBJECT_KEYS
        if (object_type, primary_value) not in objects
    ]
    if missing:
        raise RuntimeError("loan_risk 缺少必需 Ontology 对象: " + ", ".join(missing))
    return (
        _loan_account_plan(domain_id, objects[LOAN_ACCOUNT_KEY], assignee),
        _risk_snapshot_plan(domain_id, objects[RISK_SNAPSHOT_KEY], assignee),
    )


async def load_seed_context(db: Any) -> SeedContext:
    domain_rows = await db.execute_query(
        "SELECT id, domain_key, name, status FROM semantic_domain "
        "WHERE domain_key = :domain_key AND status = 'active' ORDER BY id ASC",
        {"domain_key": DOMAIN_KEY},
    )
    if not domain_rows:
        raise RuntimeError("未找到 active 的 loan_risk 领域")
    if len(domain_rows) > 1:
        domain_ids = ", ".join(str(row["id"]) for row in domain_rows)
        raise RuntimeError(f"存在多个 active 的 loan_risk 领域，无法唯一定位: {domain_ids}")
    domain_id = int(domain_rows[0]["id"])

    release_rows = await db.execute_query(
        "SELECT id, version, name, definition_hash, created_at FROM ontology_release "
        "WHERE domain_id = :domain_id ORDER BY version DESC LIMIT 1",
        {"domain_id": domain_id},
    )
    if not release_rows:
        raise RuntimeError("loan_risk 尚无 Ontology release，请先在本体建模中发布")

    actor_rows = await db.execute_query(
        "SELECT id, username, display_name, role, status FROM app_user "
        "WHERE username = :username LIMIT 1",
        {"username": ACTOR_USERNAME},
    )
    if not actor_rows:
        raise RuntimeError(
            f"未找到本地管理员 {ACTOR_USERNAME}；脚本不会自动创建账号"
        )
    actor = dict(actor_rows[0])
    if actor.get("role") != "admin" or actor.get("status") != "active":
        raise RuntimeError(f"账号 {ACTOR_USERNAME} 必须是 active 管理员")

    object_rows = await db.execute_query(
        "SELECT o.id, o.primary_value, o.display_name, o.properties, "
        "t.object_key AS object_type_key FROM ontology_object o "
        "JOIN ontology_object_type t ON t.id = o.object_type_id "
        "WHERE o.domain_id = :domain_id AND o.status = 'active' AND "
        "((t.object_key = :loan_type AND o.primary_value = :loan_primary) OR "
        "(t.object_key = :snapshot_type AND o.primary_value = :snapshot_primary))",
        {
            "domain_id": domain_id,
            "loan_type": LOAN_ACCOUNT_KEY[0],
            "loan_primary": LOAN_ACCOUNT_KEY[1],
            "snapshot_type": RISK_SNAPSHOT_KEY[0],
            "snapshot_primary": RISK_SNAPSHOT_KEY[1],
        },
    )
    objects: dict[tuple[str, str], dict[str, Any]] = {}
    for row in object_rows:
        normalized = dict(row)
        normalized["properties"] = _json_object(
            row.get("properties"),
            f"{row.get('object_type_key')}/{row.get('primary_value')}.properties",
        )
        key = (str(row["object_type_key"]), str(row["primary_value"]))
        objects[key] = normalized
    missing = [
        f"{object_type}/{primary_value}"
        for object_type, primary_value in REQUIRED_OBJECT_KEYS
        if (object_type, primary_value) not in objects
    ]
    if missing:
        raise RuntimeError("loan_risk 缺少必需 Ontology 对象: " + ", ".join(missing))

    existing_rows = await db.execute_query(
        "SELECT i.id, i.issue_key, i.status, i.version, "
        "(SELECT COUNT(*) FROM risk_evidence e "
        "WHERE e.domain_id = i.domain_id AND e.issue_id = i.id) AS evidence_count "
        "FROM risk_issue i WHERE i.domain_id = :domain_id "
        "AND i.issue_key IN (:m1_issue_key, :dti_issue_key)",
        {
            "domain_id": domain_id,
            "m1_issue_key": "demo_m1_collection_700001",
            "dti_issue_key": "demo_high_dti_600001",
        },
    )
    existing_issues = {str(row["issue_key"]): dict(row) for row in existing_rows}
    return SeedContext(
        domain_id=domain_id,
        release=dict(release_rows[0]),
        actor=actor,
        objects=objects,
        existing_issues=existing_issues,
    )


async def seed_loan_risk_delivery(
    *,
    preview: bool = False,
    db: Any | None = None,
    workflow: Any | None = None,
) -> dict[str, Any]:
    db = db or get_management_db()
    workflow = workflow or get_risk_workflow_service()
    context = await load_seed_context(db)
    plans = build_issue_plans(context.domain_id, context.objects)

    results: list[dict[str, Any]] = []
    created = 0
    skipped = 0
    planned = 0
    for plan in plans:
        issue_key = plan.issue.issue_key
        existing = context.existing_issues.get(issue_key)
        if existing is not None:
            skipped += 1
            results.append(
                {
                    "issue_key": issue_key,
                    "result": "skipped",
                    "issue_id": int(existing["id"]),
                    "status": str(existing["status"]),
                    "evidence_count": int(existing.get("evidence_count") or 0),
                    "review_action": plan.review.action,
                }
            )
            continue
        if preview:
            planned += 1
            results.append(
                {
                    "issue_key": issue_key,
                    "result": "planned",
                    "issue_id": None,
                    "status": plan.target_status,
                    "evidence_count": len(plan.evidence),
                    "review_action": plan.review.action,
                }
            )
            continue

        issue = await workflow.create_issue(plan.issue, context.actor)
        issue_id = int(issue["id"])
        for evidence in plan.evidence:
            await workflow.add_evidence(
                context.domain_id,
                issue_id,
                evidence,
                context.actor,
            )
        review_payload = plan.review.model_copy(
            update={"expected_version": int(issue.get("version") or 1)}
        )
        review_result = await workflow.review_issue(
            context.domain_id,
            issue_id,
            review_payload,
            context.actor,
        )
        status = str((review_result.get("issue") or {}).get("status") or "")
        if status != plan.target_status:
            raise RuntimeError(
                f"风险事项 {issue_key} 复核后状态异常: {status or 'missing'}"
            )
        created += 1
        results.append(
            {
                "issue_key": issue_key,
                "result": "created",
                "issue_id": issue_id,
                "status": status,
                "evidence_count": len(plan.evidence),
                "review_action": plan.review.action,
            }
        )

    return {
        "domain_id": context.domain_id,
        "domain_key": DOMAIN_KEY,
        "ontology_release": {
            "id": int(context.release["id"]),
            "version": int(context.release["version"]),
            "definition_hash": context.release.get("definition_hash"),
        },
        "preview": preview,
        "created": created,
        "skipped": skipped,
        "planned": planned,
        "issues": results,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed persistent loan_risk risk-delivery demo issues."
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="read and validate the plan without writing risk workflow records",
    )
    return parser.parse_args(argv)


async def _run_cli(preview: bool) -> dict[str, Any]:
    db = get_management_db()
    try:
        return await seed_loan_risk_delivery(
            preview=preview,
            db=db,
            workflow=get_risk_workflow_service(),
        )
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = asyncio.run(_run_cli(args.preview))
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
