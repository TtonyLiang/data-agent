"""External caller authentication, capability grants, invocation, and audit."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from copy import deepcopy
from typing import Any
from uuid import uuid4

from app.agent.ontology_tools import (
    QUERY_CAPABILITY_TOOL,
    _load_query_runtime_context,
    build_query_capability_definitions,
    invoke_ontology_tool,
)
from app.db.mysql import get_management_db
from app.models.capability_access import (
    CapabilityClientCreatePayload,
    CapabilityGrantUpsertPayload,
    CapabilityInvokePayload,
)
from app.services.datasource_service import get_datasource_service
from app.services.decision_audit_service import canonical_json, canonical_sha256
from app.services.ontology_service import get_ontology_service
from app.services.permission_service import get_permission_service
from app.services.semantic_runtime import get_semantic_runtime_service

logger = logging.getLogger(__name__)

_EXTERNAL_SQL_FIELDS = frozenset({"sql", "compiled_sql", "sql_text", "executed_sql"})
_SEMANTIC_MODEL_ERROR_CODE = "semantic_model_not_covered"
_CAPABILITY_CONTRACT_SCHEMA_VERSION = 1


class CapabilityAccessError(ValueError):
    def __init__(self, message: str, *, trace_id: str | None = None):
        super().__init__(message)
        self.trace_id = trace_id


class CapabilityAuthenticationError(CapabilityAccessError):
    pass


class CapabilityAuthorizationError(CapabilityAccessError):
    pass


class CapabilityConfigurationError(CapabilityAccessError):
    pass


class CapabilityClientNotFound(CapabilityAccessError):
    pass


def hash_capability_secret(secret: str) -> str:
    """Hash a high-entropy generated API secret for one-way storage."""
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_capability_secret(secret: str, stored_hash: str) -> bool:
    expected = hash_capability_secret(secret)
    return hmac.compare_digest(expected, str(stored_hash or ""))


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _public_client(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "secret_hash"}


def _normalize_grant(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    raw_contract = normalized.get("contract_json")
    normalized["contract_json"] = (
        _loads(raw_contract) if raw_contract not in (None, "") else None
    )
    return normalized


def _new_trace_id() -> str:
    return f"trc_{uuid4().hex[:12]}"


class CapabilityAccessService:
    async def create_client(
        self,
        payload: CapabilityClientCreatePayload,
        *,
        created_by: int,
    ) -> dict[str, Any]:
        client_key = f"cap_{secrets.token_hex(12)}"
        client_secret = secrets.token_urlsafe(32)
        client_id = await get_management_db().execute_insert(
            "INSERT INTO capability_client "
            "(client_key, name, description, secret_hash, status, created_by) "
            "VALUES (:client_key, :name, :description, :secret_hash, 'active', :created_by)",
            {
                "client_key": client_key,
                "name": payload.name,
                "description": payload.description,
                "secret_hash": hash_capability_secret(client_secret),
                "created_by": created_by,
            },
        )
        client = await self.get_client(client_id)
        return {
            "client": client,
            "client_key": client_key,
            "client_secret": client_secret,
            "secret_returned_once": True,
        }

    async def list_clients(self) -> list[dict[str, Any]]:
        rows = await get_management_db().execute_query(
            "SELECT id, client_key, name, description, status, created_by, "
            "last_used_at, created_at, updated_at FROM capability_client ORDER BY id ASC"
        )
        return [_public_client(row) for row in rows]

    async def get_client(self, client_id: int) -> dict[str, Any]:
        rows = await get_management_db().execute_query(
            "SELECT id, client_key, name, description, status, created_by, "
            "last_used_at, created_at, updated_at FROM capability_client WHERE id = :id",
            {"id": client_id},
        )
        if not rows:
            raise CapabilityClientNotFound("能力调用方不存在")
        return _public_client(rows[0])

    async def set_client_status(self, client_id: int, status: str) -> dict[str, Any]:
        await self.get_client(client_id)
        await get_management_db().execute_query(
            "UPDATE capability_client SET status = :status WHERE id = :id",
            {"id": client_id, "status": status},
        )
        return await self.get_client(client_id)

    async def authenticate_client(self, client_key: str, client_secret: str) -> dict[str, Any]:
        key = str(client_key or "").strip()
        secret = str(client_secret or "")
        if not key or not secret:
            raise CapabilityAuthenticationError("缺少能力调用凭据")
        rows = await get_management_db().execute_query(
            "SELECT * FROM capability_client WHERE client_key = :client_key LIMIT 1",
            {"client_key": key},
        )
        if not rows or not verify_capability_secret(secret, str(rows[0].get("secret_hash") or "")):
            raise CapabilityAuthenticationError("能力调用凭据无效")
        client = rows[0]
        if client.get("status") != "active":
            raise CapabilityAuthenticationError("能力调用方已停用")
        await get_management_db().execute_query(
            "UPDATE capability_client SET last_used_at = CURRENT_TIMESTAMP WHERE id = :id",
            {"id": client["id"]},
        )
        return _public_client(client)

    async def upsert_grant(
        self,
        client_id: int,
        payload: CapabilityGrantUpsertPayload,
        *,
        actor_id: int,
    ) -> dict[str, Any]:
        await self.get_client(client_id)
        existing_grant = await self._find_grant(
            client_id,
            payload.domain_id,
            payload.capability_key,
        )
        execution_agent_id = payload.execution_agent_id or (
            int(existing_grant["execution_agent_id"])
            if existing_grant and existing_grant.get("execution_agent_id")
            else None
        )
        if execution_agent_id is None:
            if payload.status == "active":
                execution_agent_id = await self._resolve_domain_permission_adapter(
                    payload.domain_id
                )
            elif existing_grant is None:
                raise CapabilityConfigurationError("能力授权不存在，无法撤销")

        binding = {
            "model_release_id": existing_grant.get("model_release_id")
            if existing_grant
            else None,
            "contract_hash": existing_grant.get("contract_hash")
            if existing_grant
            else None,
            "contract_json": existing_grant.get("contract_json")
            if existing_grant
            else None,
        }
        if payload.status == "active":
            context, runtime = await self._load_execution_context(
                payload.domain_id,
                execution_agent_id,
                payload.capability_key,
            )
            binding = self._build_contract_binding(
                payload.domain_id,
                payload.capability_key,
                context,
                runtime,
            )
        grant_id = await get_management_db().execute_insert(
            "INSERT INTO capability_grant "
            "(client_id, domain_id, capability_key, execution_agent_id, "
            "model_release_id, contract_hash, contract_json, status, created_by, updated_by) "
            "VALUES (:client_id, :domain_id, :capability_key, :execution_agent_id, "
            ":model_release_id, :contract_hash, :contract_json, :status, "
            ":actor_id, :actor_id) ON DUPLICATE KEY UPDATE "
            "id = LAST_INSERT_ID(id), execution_agent_id = VALUES(execution_agent_id), "
            "model_release_id = VALUES(model_release_id), "
            "contract_hash = VALUES(contract_hash), contract_json = VALUES(contract_json), "
            "status = VALUES(status), updated_by = VALUES(updated_by)",
            {
                "client_id": client_id,
                "domain_id": payload.domain_id,
                "capability_key": payload.capability_key,
                "execution_agent_id": execution_agent_id,
                "model_release_id": binding["model_release_id"],
                "contract_hash": binding["contract_hash"],
                "contract_json": (
                    canonical_json(binding["contract_json"])
                    if binding["contract_json"] is not None
                    else None
                ),
                "status": payload.status,
                "actor_id": actor_id,
            },
        )
        return await self.get_grant(grant_id)

    async def _find_grant(
        self,
        client_id: int,
        domain_id: int,
        capability_key: str,
    ) -> dict[str, Any] | None:
        rows = await get_management_db().execute_query(
            "SELECT * FROM capability_grant "
            "WHERE client_id = :client_id AND domain_id = :domain_id "
            "AND capability_key = :capability_key LIMIT 1",
            {
                "client_id": client_id,
                "domain_id": domain_id,
                "capability_key": capability_key,
            },
        )
        return _normalize_grant(rows[0]) if rows else None

    async def _resolve_domain_permission_adapter(self, domain_id: int) -> int | None:
        """Resolve an internal Agent only as a compatibility permission adapter.

        External callers authorize against a business domain and capability, not
        an internal validation Agent.  Until table/column policies have their own
        caller principal, this method deterministically selects a domain consumer
        that can access the domain datasource and preserves the existing policy
        enforcement path.
        """
        runtime_service = get_semantic_runtime_service()
        domain = await runtime_service.get_domain(domain_id)
        if domain is None or domain.status != "active":
            raise CapabilityConfigurationError("授权对应的业务领域不存在或未启用")
        if domain.datasource_id is None:
            raise CapabilityConfigurationError("业务领域未绑定数据源")
        permission_context = (
            await get_permission_service().resolve_domain_permission_context(
                domain_id,
                int(domain.datasource_id),
                allow_agent_fallback=False,
            )
        )
        if permission_context.source == "domain":
            return None

        datasource_service = get_datasource_service()
        first = await runtime_service.resolve_domain_agent(domain_id)
        if first is not None and await datasource_service.belongs_to_agent(
            int(domain.datasource_id), int(first)
        ):
            return int(first)

        for agent_id in await runtime_service.get_domain_agent_ids(domain_id):
            if agent_id == first:
                continue
            if await datasource_service.belongs_to_agent(
                int(domain.datasource_id), int(agent_id)
            ):
                return int(agent_id)
        raise CapabilityConfigurationError(
            "当前业务领域没有可用的数据权限边界，请先完成领域数据源权限配置"
        )

    async def get_grant(self, grant_id: int) -> dict[str, Any]:
        rows = await get_management_db().execute_query(
            "SELECT * FROM capability_grant WHERE id = :id",
            {"id": grant_id},
        )
        if not rows:
            raise CapabilityAccessError("能力授权不存在")
        return _normalize_grant(rows[0])

    async def list_grants(self, client_id: int) -> list[dict[str, Any]]:
        await self.get_client(client_id)
        rows = await get_management_db().execute_query(
            "SELECT * FROM capability_grant WHERE client_id = :client_id "
            "ORDER BY domain_id, capability_key",
            {"client_id": client_id},
        )
        return [_normalize_grant(row) for row in rows]

    async def invoke(
        self,
        client: dict[str, Any],
        capability_key: str,
        payload: CapabilityInvokePayload,
    ) -> dict[str, Any]:
        started_at = time.monotonic()
        trace_id = _new_trace_id()
        client_id = int(client["id"])
        grant = await self._find_active_grant(client_id, payload.domain_id, capability_key)
        request_summary = self._request_summary(payload)
        if grant is None:
            message = "调用方未获得该业务领域的能力授权"
            await self._safe_write_audit(
                trace_id=trace_id,
                client_id=client_id,
                grant=None,
                domain_id=payload.domain_id,
                capability_key=capability_key,
                status="permission_blocked",
                latency_ms=self._latency_ms(started_at),
                error_category="authorization",
                error_message=message,
                request_summary=request_summary,
            )
            raise CapabilityAuthorizationError(message, trace_id=trace_id)

        try:
            grant_release_id = (
                int(grant["model_release_id"])
                if grant.get("model_release_id")
                else None
            )
            if (
                grant_release_id is not None
                and payload.model_release_id is not None
                and grant_release_id != payload.model_release_id
            ):
                raise CapabilityConfigurationError(
                    "请求的企业模型版本与能力授权合同不一致"
                )
            context, runtime = await self._load_execution_context(
                payload.domain_id,
                (
                    int(grant["execution_agent_id"])
                    if grant.get("execution_agent_id")
                    else None
                ),
                capability_key,
                model_release_id=grant_release_id or payload.model_release_id,
            )
            current_binding = self._build_contract_binding(
                payload.domain_id,
                capability_key,
                context,
                runtime,
            )
            grant = await self._ensure_grant_contract(grant, current_binding)
            result = await invoke_ontology_tool(
                get_ontology_service(),
                payload.domain_id,
                QUERY_CAPABILITY_TOOL,
                {
                    "capability_key": capability_key,
                    "logic_form": payload.logic_form.model_dump(mode="python"),
                },
                {
                    "id": None,
                    "username": client.get("client_key"),
                    "display_name": client.get("name"),
                    "role": "user",
                    "caller_type": "capability_client",
                    "client_id": client_id,
                },
                ontology_context=context,
                semantic_runtime=runtime,
            )
            self._reject_external_nl2sql_fallback(result)
        except CapabilityConfigurationError as exc:
            await self._write_failure_audit(
                trace_id, client_id, grant, payload, capability_key, started_at, exc,
                status="permission_blocked", category="configuration",
            )
            exc.trace_id = trace_id
            raise
        except PermissionError as exc:
            await self._write_failure_audit(
                trace_id, client_id, grant, payload, capability_key, started_at, exc,
                status="permission_blocked", category="permission",
            )
            raise CapabilityAuthorizationError(str(exc), trace_id=trace_id) from exc
        except ValueError as exc:
            await self._write_failure_audit(
                trace_id, client_id, grant, payload, capability_key, started_at, exc,
                status="validation_blocked", category="validation",
            )
            raise CapabilityAccessError(str(exc), trace_id=trace_id) from exc
        except Exception as exc:
            await self._write_failure_audit(
                trace_id, client_id, grant, payload, capability_key, started_at, exc,
                status="failed", category="runtime",
            )
            raise CapabilityAccessError("能力调用失败", trace_id=trace_id) from exc

        execution = dict(result.get("execution") or {})
        result_trace = dict(result.get("execution_trace") or {})
        trace_id = str(result_trace.get("trace_id") or trace_id)
        status = str(execution.get("status") or "failed")
        if status == "validation_blocked" and not execution.get("error_category"):
            execution["error_category"] = "semantic_model"
        sql_rows = result.get("sql_result") or []
        row_count = len(sql_rows) if isinstance(sql_rows, list) else 0
        error_message = str(result.get("sql_error") or "").strip() or None
        latency_ms = self._latency_ms(started_at)
        release = result_trace.get("ontology_release") or {}
        model_release = result_trace.get("model_release") or {}
        semantic_snapshot = result_trace.get("semantic_snapshot") or {}
        model_release_id = (
            model_release.get("id") if isinstance(model_release, dict) else None
        ) or grant.get("model_release_id")
        semantic_snapshot_id = (
            semantic_snapshot.get("id")
            if isinstance(semantic_snapshot, dict)
            else None
        )
        ontology_release_id = release.get("id") if isinstance(release, dict) else None
        result_summary = {
            "executed": bool(execution.get("executed")),
            "attempted": bool(execution.get("attempted")),
            "row_count": row_count,
            "columns": (
                list(sql_rows[0].keys())
                if row_count and isinstance(sql_rows[0], dict)
                else []
            ),
            "target_object": result_trace.get("target_object"),
            "grant_contract_hash": grant.get("contract_hash"),
            "permission_source": (
                (result_trace.get("permission") or {}).get("subject", {}).get("source")
                if isinstance(result_trace.get("permission"), dict)
                else None
            ),
        }
        audit_recorded = await self._safe_write_audit(
            trace_id=trace_id,
            client_id=client_id,
            grant=grant,
            domain_id=payload.domain_id,
            capability_key=capability_key,
            status=status,
            latency_ms=latency_ms,
            row_count=row_count,
            model_release_id=model_release_id,
            semantic_snapshot_id=semantic_snapshot_id,
            ontology_release_id=ontology_release_id,
            error_category=execution.get("error_category"),
            error_message=error_message,
            request_summary=request_summary,
            result_summary=result_summary,
        )
        public_result = self._sanitize_external_result(result, trace_id, status)
        public_trace = dict(public_result.get("execution_trace") or {})
        public_trace["capability_audit"] = {"recorded": audit_recorded}
        public_result["execution_trace"] = public_trace
        return {
            "trace_id": trace_id,
            "domain_id": payload.domain_id,
            "capability_key": capability_key,
            "status": status,
            "latency_ms": latency_ms,
            "result": public_result,
        }

    async def list_invocation_audits(
        self,
        *,
        client_id: int | None = None,
        domain_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions = []
        params: dict[str, Any] = {"limit": limit}
        if client_id is not None:
            conditions.append("client_id = :client_id")
            params["client_id"] = client_id
        if domain_id is not None:
            conditions.append("domain_id = :domain_id")
            params["domain_id"] = domain_id
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await get_management_db().execute_query(
            "SELECT * FROM capability_invocation_audit"
            f"{where} ORDER BY id DESC LIMIT :limit",
            params,
        )
        for row in rows:
            row["request_summary"] = _loads(row.get("request_summary"))
            row["result_summary"] = _loads(row.get("result_summary"))
            row["latency_ms"] = float(row.get("latency_ms") or 0)
        return rows

    async def _find_active_grant(
        self, client_id: int, domain_id: int, capability_key: str
    ) -> dict[str, Any] | None:
        rows = await get_management_db().execute_query(
            "SELECT * FROM capability_grant WHERE client_id = :client_id "
            "AND domain_id = :domain_id AND capability_key = :capability_key "
            "AND status = 'active' LIMIT 1",
            {
                "client_id": client_id,
                "domain_id": domain_id,
                "capability_key": capability_key,
            },
        )
        return _normalize_grant(rows[0]) if rows else None

    @staticmethod
    def _build_contract_binding(
        domain_id: int,
        capability_key: str,
        context: dict[str, Any],
        runtime: Any,
    ) -> dict[str, Any]:
        release = context.get("model_release") or {}
        release_id = release.get("id") if isinstance(release, dict) else None
        if not release_id:
            raise CapabilityConfigurationError("业务领域尚未激活统一企业模型版本")
        capabilities = build_query_capability_definitions(runtime, context)
        contract = next(
            (item for item in capabilities if item.get("key") == capability_key),
            None,
        )
        if contract is None:
            raise CapabilityConfigurationError("业务领域未发布该 Query Capability")
        runtime_domain = getattr(runtime, "domain", None)
        datasource_id = (
            runtime_domain.get("datasource_id")
            if isinstance(runtime_domain, dict)
            else getattr(runtime_domain, "datasource_id", None)
        )
        snapshot = {
            "schema_version": _CAPABILITY_CONTRACT_SCHEMA_VERSION,
            "kind": "query_capability",
            "domain_id": int(domain_id),
            "model_release": {
                "id": int(release_id),
                "model_hash": str(release.get("model_hash") or ""),
            },
            "data_policy": {
                "strategy": "live_source",
                "source": {
                    "kind": "business_datasource",
                    "datasource_id": int(datasource_id) if datasource_id else None,
                },
                "as_of": {"mode": "invocation_time"},
                "uses_twin_snapshot": False,
            },
            "capability": contract,
        }
        return {
            "model_release_id": int(release_id),
            "contract_hash": canonical_sha256(snapshot),
            "contract_json": snapshot,
        }

    async def _ensure_grant_contract(
        self,
        grant: dict[str, Any],
        current_binding: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate a frozen contract or lazily bind one legacy grant."""
        stored_release_id = grant.get("model_release_id")
        stored_hash = str(grant.get("contract_hash") or "").strip().lower()
        stored_contract = grant.get("contract_json")
        if not stored_release_id or not stored_hash or not isinstance(stored_contract, dict):
            await get_management_db().execute_query(
                "UPDATE capability_grant SET model_release_id = :model_release_id, "
                "contract_hash = :contract_hash, contract_json = :contract_json "
                "WHERE id = :id",
                {
                    "id": grant["id"],
                    "model_release_id": current_binding["model_release_id"],
                    "contract_hash": current_binding["contract_hash"],
                    "contract_json": canonical_json(current_binding["contract_json"]),
                },
            )
            return {**grant, **current_binding}

        if int(stored_release_id) != int(current_binding["model_release_id"]):
            raise CapabilityConfigurationError(
                "当前激活企业模型版本与能力授权合同不一致，请重新授权"
            )
        if canonical_sha256(stored_contract) != stored_hash:
            raise CapabilityConfigurationError("能力授权合同快照校验失败")
        if stored_hash != current_binding["contract_hash"]:
            raise CapabilityConfigurationError(
                "当前 Query Capability 合同与授权快照不一致，请重新授权"
            )
        return grant

    async def _load_execution_context(
        self,
        domain_id: int,
        execution_agent_id: int | None,
        capability_key: str,
        *,
        model_release_id: int | None = None,
    ):
        runtime_service = get_semantic_runtime_service()
        domain = await runtime_service.get_domain(domain_id)
        if domain is None or domain.status != "active":
            raise CapabilityConfigurationError("授权对应的业务领域不存在或未启用")
        if domain.datasource_id is None:
            raise CapabilityConfigurationError("业务领域未绑定数据源")
        permission_context = (
            await get_permission_service().resolve_domain_permission_context(
                domain_id,
                int(domain.datasource_id),
                compatibility_agent_id=execution_agent_id,
                allow_agent_fallback=bool(execution_agent_id),
            )
        )
        if permission_context.source == "unconfigured":
            raise CapabilityConfigurationError("业务领域尚未配置数据权限")
        if permission_context.source == "agent_compatibility":
            if not execution_agent_id or not await runtime_service.is_domain_bound_to_agent(
                domain_id, execution_agent_id
            ):
                raise CapabilityConfigurationError("兼容权限智能体未绑定该业务领域")
            if not await get_datasource_service().belongs_to_agent(
                int(domain.datasource_id), execution_agent_id
            ):
                raise CapabilityConfigurationError("兼容权限智能体无权访问领域数据源")
        context, runtime = await _load_query_runtime_context(
            get_ontology_service(),
            domain_id,
            {"role": "user"},
        )
        if execution_agent_id is not None:
            runtime.domain.agent_id = execution_agent_id
        context["data_permission"] = permission_context.metadata()
        active_release = context.get("model_release") or {}
        active_release_id = (
            active_release.get("id") if isinstance(active_release, dict) else None
        )
        if not active_release_id:
            raise CapabilityConfigurationError("业务领域尚未激活统一企业模型版本")
        if model_release_id is not None and int(active_release_id or 0) != model_release_id:
            raise CapabilityConfigurationError("请求的企业模型版本不是当前激活版本")
        capabilities = build_query_capability_definitions(runtime, context)
        if capability_key not in {item.get("key") for item in capabilities}:
            raise CapabilityConfigurationError("业务领域未发布该 Query Capability")
        return context, runtime

    @staticmethod
    def _request_summary(payload: CapabilityInvokePayload) -> dict[str, Any]:
        logic_form = payload.logic_form
        return {
            "metrics": list(logic_form.metrics),
            "dimensions": list(logic_form.dimensions),
            "filters": [
                {"field": item.field, "operator": item.operator}
                for item in logic_form.filters
            ],
            "time_range_type": logic_form.time_range.type if logic_form.time_range else None,
            "time_range_period": logic_form.time_range.period if logic_form.time_range else None,
            "grain": logic_form.grain,
            "sort": [item.model_dump() for item in logic_form.sort],
            "limit": logic_form.limit,
            "model_release_id": payload.model_release_id,
        }

    @staticmethod
    def _latency_ms(started_at: float) -> float:
        return round((time.monotonic() - started_at) * 1000, 2)

    async def _write_failure_audit(
        self,
        trace_id: str,
        client_id: int,
        grant: dict[str, Any],
        payload: CapabilityInvokePayload,
        capability_key: str,
        started_at: float,
        exc: Exception,
        *,
        status: str,
        category: str,
    ) -> bool:
        return await self._safe_write_audit(
            trace_id=trace_id,
            client_id=client_id,
            grant=grant,
            domain_id=payload.domain_id,
            capability_key=capability_key,
            status=status,
            latency_ms=self._latency_ms(started_at),
            error_category=category,
            error_message=str(exc),
            request_summary=self._request_summary(payload),
            model_release_id=(
                grant.get("model_release_id") or payload.model_release_id
            ),
        )

    async def _safe_write_audit(self, **kwargs: Any) -> bool:
        try:
            await self._write_audit(**kwargs)
            return True
        except Exception:
            logger.exception(
                "capability invocation audit write failed trace_id=%s",
                kwargs.get("trace_id"),
            )
            return False

    @staticmethod
    def _reject_external_nl2sql_fallback(result: dict[str, Any]) -> None:
        """Keep the external capability path on published semantic contracts only."""
        execution = result.get("execution") or {}
        trace = result.get("execution_trace") or {}
        query_execution = (
            trace.get("query_capability_execution") or {}
            if isinstance(trace, dict)
            else {}
        )
        strategies = {
            str(execution.get("mode") or "").strip().lower()
            if isinstance(execution, dict)
            else "",
            str(trace.get("compile_strategy") or "").strip().lower()
            if isinstance(trace, dict)
            else "",
            str(query_execution.get("mode") or "").strip().lower()
            if isinstance(query_execution, dict)
            else "",
        }
        if "nl2sql_fallback" in strategies:
            raise ValueError(
                "请求未被当前已发布企业模型覆盖；外部 Query Capability 禁止使用 NL2SQL 兜底"
            )

    @staticmethod
    def _sanitize_external_result(
        result: dict[str, Any], trace_id: str, status: str
    ) -> dict[str, Any]:
        public_result = CapabilityAccessService._strip_physical_sql(deepcopy(result))
        if status == "validation_blocked":
            validation = public_result.get("validation") or {}
            errors = (
                list(validation.get("errors") or [])
                if isinstance(validation, dict)
                else []
            )
            message = "请求未被当前已发布企业模型覆盖，未执行查询。"
            public_result["error"] = {
                "code": _SEMANTIC_MODEL_ERROR_CODE,
                "category": "semantic_model",
                "message": message,
                "details": {
                    "validation_errors": errors,
                    "fallback_allowed": False,
                },
            }
            execution = dict(public_result.get("execution") or {})
            execution.update(
                {
                    "executed": False,
                    "attempted": False,
                    "error_category": "semantic_model",
                    "message": message,
                }
            )
            public_result["execution"] = execution
            public_result["final_answer"] = message
        elif status == "database_error":
            message = (
                "业务数据查询失败，请联系平台管理员并提供 trace_id "
                f"{trace_id}"
            )
            public_result["sql_error"] = message
            public_result["final_answer"] = message
            execution = dict(public_result.get("execution") or {})
            execution["message"] = message
            public_result["execution"] = execution
            trace = dict(public_result.get("execution_trace") or {})
            if "sql_execution" in trace:
                trace["sql_execution"] = {"failed": True}
            public_result["execution_trace"] = trace
        return public_result

    @staticmethod
    def _strip_physical_sql(value: Any) -> Any:
        """Remove physical SQL statements from an external response payload."""
        if isinstance(value, dict):
            return {
                key: CapabilityAccessService._strip_physical_sql(item)
                for key, item in value.items()
                if key not in _EXTERNAL_SQL_FIELDS
            }
        if isinstance(value, list):
            return [CapabilityAccessService._strip_physical_sql(item) for item in value]
        return value

    async def _write_audit(
        self,
        *,
        trace_id: str,
        client_id: int,
        grant: dict[str, Any] | None,
        domain_id: int,
        capability_key: str,
        status: str,
        latency_ms: float,
        row_count: int = 0,
        model_release_id: int | None = None,
        semantic_snapshot_id: int | None = None,
        ontology_release_id: int | None = None,
        error_category: str | None = None,
        error_message: str | None = None,
        request_summary: dict[str, Any] | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> None:
        await get_management_db().execute_insert(
            "INSERT INTO capability_invocation_audit "
            "(trace_id, client_id, grant_id, domain_id, capability_key, "
            "execution_agent_id, model_release_id, semantic_snapshot_id, "
            "ontology_release_id, status, latency_ms, row_count, "
            "error_category, error_message, request_summary, result_summary) VALUES "
            "(:trace_id, :client_id, :grant_id, :domain_id, :capability_key, "
            ":execution_agent_id, :model_release_id, :semantic_snapshot_id, "
            ":ontology_release_id, :status, :latency_ms, :row_count, "
            ":error_category, :error_message, :request_summary, :result_summary)",
            {
                "trace_id": trace_id,
                "client_id": client_id,
                "grant_id": grant.get("id") if grant else None,
                "domain_id": domain_id,
                "capability_key": capability_key,
                "execution_agent_id": grant.get("execution_agent_id") if grant else None,
                "model_release_id": model_release_id,
                "semantic_snapshot_id": semantic_snapshot_id,
                "ontology_release_id": ontology_release_id,
                "status": status,
                "latency_ms": latency_ms,
                "row_count": row_count,
                "error_category": error_category,
                "error_message": str(error_message or "")[:2000] or None,
                "request_summary": json.dumps(request_summary or {}, ensure_ascii=False),
                "result_summary": json.dumps(result_summary or {}, ensure_ascii=False),
            },
        )


_service: CapabilityAccessService | None = None


def get_capability_access_service() -> CapabilityAccessService:
    global _service
    if _service is None:
        _service = CapabilityAccessService()
    return _service
