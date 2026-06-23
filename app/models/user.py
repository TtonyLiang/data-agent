"""用户与登录认证数据模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


UserRole = Literal["admin", "user"]
UserStatus = Literal["active", "disabled"]


class PublicUser(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    role: UserRole
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
    role: UserRole = "user"
    status: UserStatus = "active"


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    role: UserRole = "user"
    status: UserStatus = "active"
    must_change_password: bool = False


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)
    must_change_password: bool = True


class UserAgentPermissionUpdate(BaseModel):
    agent_ids: list[int] = Field(default_factory=list)
