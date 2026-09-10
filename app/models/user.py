"""用户与登录认证数据模型。

The product-facing roles are ``business`` (业务人员) and ``technical``
(技术工程师).  ``admin`` and ``user`` remain accepted as compatibility values
for the existing demo and old installations; they are not a new product role
model.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

UserRole = Literal["admin", "user", "business", "technical"]
UserStatus = Literal["active", "disabled"]

ROLE_LABELS: dict[str, str] = {
    "business": "业务人员",
    "technical": "技术工程师",
    "admin": "管理员（技术工程师兼容）",
    "user": "业务人员（旧账号兼容）",
}

# Stable capability names are deliberately small.  They are used by the UI
# and API dependencies; they do not attempt to become a general RBAC system.
ROLE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "business": (
        "model_edit",
        "model_submit",
        "domain_read",
        "capability_validate",
        "risk_review",
    ),
    "technical": (
        "model_edit",
        "model_submit",
        "data_source_manage",
        "schema_manage",
        "mapping_manage",
        "twin_sync",
        "model_publish",
        "capability_validate",
        "agent_debug",
        "platform_config",
        "domain_read",
        "risk_review",
    ),
    "admin": (
        "model_edit",
        "model_submit",
        "data_source_manage",
        "schema_manage",
        "mapping_manage",
        "twin_sync",
        "model_publish",
        "capability_validate",
        "agent_debug",
        "platform_config",
        "user_manage",
        "domain_read",
        "risk_review",
    ),
    # Legacy ``user`` keeps the old validation-client behavior.
    "user": ("domain_read", "capability_validate", "risk_review"),
}


def role_label(role: str | None) -> str:
    """Return the product-facing label for a stored role value."""
    return ROLE_LABELS.get(str(role or "user"), str(role or "user"))


def role_capabilities(role: str | None) -> list[str]:
    """Return the small, stable capability set exposed to clients."""
    return list(ROLE_CAPABILITIES.get(str(role or "user"), ()))


def is_business_role(role: str | None) -> bool:
    return str(role or "") in {"business", "user"}


def is_technical_role(role: str | None) -> bool:
    return str(role or "") in {"technical", "admin"}


def is_model_editor_role(role: str | None) -> bool:
    return str(role or "") in {"business", "technical", "admin"}


def is_model_publisher_role(role: str | None) -> bool:
    return str(role or "") in {"technical", "admin"}


def ontology_action_role(role: str | None) -> str:
    """Map product roles to the legacy ``allowed_roles`` action contract."""
    return "admin" if is_technical_role(role) else "user"


class PublicUser(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    role: UserRole
    role_label: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    status: UserStatus
    must_change_password: bool = False
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None
    last_login_at: datetime | str | None = None


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: PublicUser


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    role: UserRole = "business"
    status: UserStatus = "active"


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    role: UserRole = "business"
    status: UserStatus = "active"
    must_change_password: bool = False


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)
    must_change_password: bool = True


class UserAgentPermissionUpdate(BaseModel):
    agent_ids: list[int] = Field(default_factory=list)
