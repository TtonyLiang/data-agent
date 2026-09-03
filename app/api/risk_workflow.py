"""REST API for risk review, report delivery, and decision audit."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user, require_admin, require_domain_access
from app.models.risk_workflow import (
    ChatRiskIssueCreatePayload,
    EvidenceCreatePayload,
    ReportCreatePayload,
    ReportFinalizePayload,
    ReportVersionCreatePayload,
    RiskIssueCreatePayload,
    RiskIssueStatus,
    RiskReviewPayload,
    RiskSeverity,
)
from app.models.user import PublicUser
from app.services.decision_audit_service import get_decision_audit_service
from app.services.risk_workflow_service import (
    RiskWorkflowConflict,
    RiskWorkflowNotFound,
    get_risk_workflow_service,
)

router = APIRouter()


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _conflict(exc: RiskWorkflowConflict) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _not_found(exc: RiskWorkflowNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("/domains/{domain_id}/summary")
async def get_summary(
    domain_id: int, current_user: PublicUser = Depends(get_current_user)
):
    await require_domain_access(domain_id, current_user)
    return await get_risk_workflow_service().get_summary(domain_id)


@router.get("/domains/{domain_id}/issues")
async def list_issues(
    domain_id: int,
    status: RiskIssueStatus | None = None,
    severity: RiskSeverity | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    return {
        "issues": await get_risk_workflow_service().list_issues(
            domain_id,
            status=status,
            severity=severity,
            limit=limit,
            offset=offset,
        )
    }


@router.post("/domains/{domain_id}/issues", status_code=201)
async def create_issue(
    domain_id: int,
    payload: RiskIssueCreatePayload,
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    try:
        return await get_risk_workflow_service().create_issue(
            payload, current_user.model_dump()
        )
    except RiskWorkflowConflict as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/domains/{domain_id}/issues/from-chat", status_code=201)
async def create_issue_from_chat(
    domain_id: int,
    payload: ChatRiskIssueCreatePayload,
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    try:
        return await get_risk_workflow_service().create_issue_from_chat(
            payload, current_user.model_dump()
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RiskWorkflowNotFound as exc:
        raise _not_found(exc) from exc
    except RiskWorkflowConflict as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/domains/{domain_id}/issues/{issue_id}")
async def get_issue(
    domain_id: int,
    issue_id: int,
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    try:
        return await get_risk_workflow_service().get_issue(domain_id, issue_id)
    except RiskWorkflowNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/domains/{domain_id}/issues/{issue_id}/evidence", status_code=201)
async def add_evidence(
    domain_id: int,
    issue_id: int,
    payload: EvidenceCreatePayload,
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    try:
        return await get_risk_workflow_service().add_evidence(
            domain_id, issue_id, payload, current_user.model_dump()
        )
    except RiskWorkflowNotFound as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/domains/{domain_id}/issues/{issue_id}/reviews", status_code=201)
async def review_issue(
    domain_id: int,
    issue_id: int,
    payload: RiskReviewPayload,
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    try:
        return await get_risk_workflow_service().review_issue(
            domain_id, issue_id, payload, current_user.model_dump()
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RiskWorkflowNotFound as exc:
        raise _not_found(exc) from exc
    except RiskWorkflowConflict as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/domains/{domain_id}/reports")
async def list_reports(
    domain_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    return {
        "reports": await get_risk_workflow_service().list_reports(
            domain_id, limit=limit, offset=offset
        )
    }


@router.post("/domains/{domain_id}/reports", status_code=201)
async def create_report(
    domain_id: int,
    payload: ReportCreatePayload,
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    if payload.domain_id != domain_id:
        raise HTTPException(status_code=400, detail="请求路径与领域 ID 不一致")
    try:
        return await get_risk_workflow_service().create_report(
            payload, current_user.model_dump()
        )
    except RiskWorkflowConflict as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/domains/{domain_id}/reports/{report_id}/versions")
async def list_report_versions(
    domain_id: int,
    report_id: int,
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    try:
        versions = await get_risk_workflow_service().list_report_versions(
            domain_id, report_id
        )
        return {"versions": versions}
    except RiskWorkflowNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/domains/{domain_id}/reports/{report_id}/versions", status_code=201)
async def create_report_version(
    domain_id: int,
    report_id: int,
    payload: ReportVersionCreatePayload,
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    try:
        return await get_risk_workflow_service().create_report_version(
            domain_id, report_id, payload, current_user.model_dump()
        )
    except RiskWorkflowNotFound as exc:
        raise _not_found(exc) from exc
    except RiskWorkflowConflict as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/domains/{domain_id}/reports/{report_id}/finalize")
async def finalize_report(
    domain_id: int,
    report_id: int,
    payload: ReportFinalizePayload,
    current_user: PublicUser = Depends(require_admin),
):
    await require_domain_access(domain_id, current_user)
    try:
        return await get_risk_workflow_service().finalize_report(
            domain_id, report_id, payload, current_user.model_dump()
        )
    except RiskWorkflowNotFound as exc:
        raise _not_found(exc) from exc
    except RiskWorkflowConflict as exc:
        raise _conflict(exc) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/domains/{domain_id}/audit")
async def list_audit_events(
    domain_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: PublicUser = Depends(get_current_user),
):
    await require_domain_access(domain_id, current_user)
    events = await get_decision_audit_service().list_events(
        domain_id, limit=limit, offset=offset
    )
    return {"events": events}


@router.get("/domains/{domain_id}/audit/verify")
async def verify_audit_chain(
    domain_id: int, current_user: PublicUser = Depends(get_current_user)
):
    await require_domain_access(domain_id, current_user)
    return await get_decision_audit_service().verify_chain(domain_id)
