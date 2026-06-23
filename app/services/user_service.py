"""用户、认证与用户-智能体授权服务。"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.config import get_settings
from app.db.mysql import get_management_db
from app.models.user import PublicUser, UserCreate, UserUpdate

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24


class AuthError(ValueError):
    """认证失败。"""


class PermissionDenied(ValueError):
    """权限不足。"""


def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码。"""
    if len(password.encode("utf-8")) > 72:
        raise ValueError("密码过长，请控制在 72 字节以内")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码与 bcrypt 哈希。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def public_user_from_row(row: dict[str, Any]) -> PublicUser:
    """把数据库行转换成安全出参。"""
    return PublicUser(
        id=int(row["id"]),
        username=str(row["username"]),
        display_name=row.get("display_name"),
        role=row.get("role") or "user",
        status=row.get("status") or "active",
        must_change_password=bool(row.get("must_change_password")),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        last_login_at=row.get("last_login_at"),
    )


class UserService:
    """用户管理和授权查询服务。"""

    async def create_user(self, payload: UserCreate, *, must_change_password: bool = False) -> int:
        db = get_management_db()
        existing = await self.get_user_by_username(payload.username)
        if existing:
            raise ValueError("用户名已存在")
        return await db.execute_insert(
            "INSERT INTO app_user "
            "(username, password_hash, display_name, role, status, must_change_password) "
            "VALUES (:username, :password_hash, :display_name, :role, :status, :must_change)",
            {
                "username": payload.username.strip(),
                "password_hash": hash_password(payload.password),
                "display_name": payload.display_name or payload.username.strip(),
                "role": payload.role,
                "status": payload.status,
                "must_change": int(must_change_password),
            },
        )

    async def register_user(self, username: str, password: str, display_name: str | None = None) -> PublicUser:
        user_id = await self.create_user(
            UserCreate(
                username=username,
                password=password,
                display_name=display_name or username,
                role="user",
                status="active",
            )
        )
        user = await self.get_user_by_id(user_id)
        if not user:
            raise AuthError("注册失败")
        return public_user_from_row(user)

    async def authenticate(self, username: str, password: str) -> tuple[str, PublicUser]:
        user = await self.get_user_by_username(username)
        if not user or not verify_password(password, str(user.get("password_hash") or "")):
            raise AuthError("用户名或密码错误")
        if user.get("status") != "active":
            raise PermissionDenied("用户已被禁用")
        await get_management_db().execute_query(
            "UPDATE app_user SET last_login_at = CURRENT_TIMESTAMP WHERE id = :id",
            {"id": user["id"]},
        )
        public = public_user_from_row({**user, "last_login_at": datetime.now(UTC).isoformat()})
        return self.create_access_token(public), public

    def create_access_token(self, user: PublicUser) -> str:
        secret = self._jwt_secret()
        now = datetime.now(UTC)
        payload = {
            "sub": str(user.id),
            "username": user.username,
            "role": user.role,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=JWT_EXPIRE_HOURS)).timestamp()),
        }
        return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)

    def decode_access_token(self, token: str) -> dict[str, Any]:
        secret = self._jwt_secret()
        try:
            payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        except jwt.PyJWTError as exc:
            raise AuthError("登录态无效或已过期") from exc
        return payload

    def _jwt_secret(self) -> str:
        settings = get_settings()
        secret = (settings.jwt_secret_key or "").strip()
        if len(secret.encode("utf-8")) >= 32:
            return secret
        if not settings.debug:
            raise AuthError("服务未配置安全的 JWT 密钥")
        if secret:
            logger.warning("configured JWT secret is too short; using local debug JWT secret")
        # Generate a random secret for debug mode (changes on each restart)
        return secrets.token_hex(32)

    async def get_user_by_token(self, token: str) -> PublicUser:
        payload = self.decode_access_token(token)
        user_id = int(payload.get("sub") or 0)
        row = await self.get_user_by_id(user_id)
        if not row:
            raise AuthError("用户不存在")
        if row.get("status") != "active":
            raise PermissionDenied("用户已被禁用")
        return public_user_from_row(row)

    async def list_users(self) -> list[PublicUser]:
        rows = await get_management_db().execute_query(
            "SELECT id, username, display_name, role, status, must_change_password, "
            "created_at, updated_at, last_login_at FROM app_user ORDER BY id ASC"
        )
        return [public_user_from_row(row) for row in rows]

    async def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        rows = await get_management_db().execute_query(
            "SELECT * FROM app_user WHERE id = :id",
            {"id": user_id},
        )
        return rows[0] if rows else None

    async def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        rows = await get_management_db().execute_query(
            "SELECT * FROM app_user WHERE username = :username",
            {"username": username.strip()},
        )
        return rows[0] if rows else None

    async def update_user(self, user_id: int, payload: UserUpdate) -> PublicUser | None:
        db = get_management_db()
        await db.execute_query(
            "UPDATE app_user SET display_name = :display_name, role = :role, status = :status, "
            "must_change_password = :must_change WHERE id = :id",
            {
                "id": user_id,
                "display_name": payload.display_name,
                "role": payload.role,
                "status": payload.status,
                "must_change": int(payload.must_change_password),
            },
        )
        row = await self.get_user_by_id(user_id)
        return public_user_from_row(row) if row else None

    async def set_status(self, user_id: int, status: str) -> PublicUser | None:
        await get_management_db().execute_query(
            "UPDATE app_user SET status = :status WHERE id = :id",
            {"id": user_id, "status": status},
        )
        row = await self.get_user_by_id(user_id)
        return public_user_from_row(row) if row else None

    async def reset_password(
        self, user_id: int, password: str, *, must_change_password: bool = True
    ) -> bool:
        await get_management_db().execute_query(
            "UPDATE app_user SET password_hash = :password_hash, must_change_password = :must_change "
            "WHERE id = :id",
            {
                "id": user_id,
                "password_hash": hash_password(password),
                "must_change": int(must_change_password),
            },
        )
        return bool(await self.get_user_by_id(user_id))

    async def get_user_agent_ids(self, user_id: int) -> list[int]:
        rows = await get_management_db().execute_query(
            "SELECT agent_id FROM user_agent_permission WHERE user_id = :user_id ORDER BY agent_id ASC",
            {"user_id": user_id},
        )
        return [int(row["agent_id"]) for row in rows]

    async def set_user_agent_ids(self, user_id: int, agent_ids: list[int]) -> list[int]:
        ids = sorted({int(agent_id) for agent_id in agent_ids if int(agent_id) > 0})
        statements = [
            ("DELETE FROM user_agent_permission WHERE user_id = :user_id", {"user_id": user_id})
        ]
        statements.extend(
            (
                "INSERT INTO user_agent_permission (user_id, agent_id) VALUES (:user_id, :agent_id)",
                {"user_id": user_id, "agent_id": agent_id},
            )
            for agent_id in ids
        )
        await get_management_db().execute_transaction(statements)
        return await self.get_user_agent_ids(user_id)

    async def can_access_agent(self, user: PublicUser, agent_id: int) -> bool:
        if user.role == "admin":
            return True
        rows = await get_management_db().execute_query(
            "SELECT 1 FROM user_agent_permission WHERE user_id = :user_id AND agent_id = :agent_id",
            {"user_id": user.id, "agent_id": agent_id},
        )
        return bool(rows)


_user_service: UserService | None = None


def get_user_service() -> UserService:
    global _user_service
    if _user_service is None:
        _user_service = UserService()
    return _user_service
