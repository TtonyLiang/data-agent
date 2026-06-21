from __future__ import annotations

import base64
import hashlib

from app.config import get_settings

ENCRYPTED_PREFIX = "enc:v1:"


class SecretServiceError(RuntimeError):
    pass


class SecretService:
    """Encrypt and decrypt secrets stored in management tables."""

    def __init__(self) -> None:
        self._fernet = None

    def encrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        if value.startswith(ENCRYPTED_PREFIX):
            return value
        if value == "":
            return value
        return ENCRYPTED_PREFIX + self._get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith(ENCRYPTED_PREFIX):
            return value
        token = value[len(ENCRYPTED_PREFIX) :].encode("utf-8")
        try:
            return self._get_fernet().decrypt(token).decode("utf-8")
        except Exception as exc:  # pragma: no cover - concrete Fernet errors vary by version.
            raise SecretServiceError("密钥解密失败，请检查 SECRET_ENCRYPTION_KEY") from exc

    def _get_fernet(self):
        if self._fernet is not None:
            return self._fernet
        settings = get_settings()
        raw_key = (settings.secret_encryption_key or "").strip()
        if not raw_key and settings.debug:
            raw_key = "wenqu-development-secret-key"
        try:
            from cryptography.fernet import Fernet
        except ModuleNotFoundError as exc:
            if settings.debug:
                self._fernet = DevelopmentFernet(normalize_fernet_key(raw_key))
                return self._fernet
            raise SecretServiceError(
                "缺少 cryptography 依赖，无法加密保存密钥"
            ) from exc

        if not raw_key:
            raise SecretServiceError("未配置 SECRET_ENCRYPTION_KEY，无法加密保存密钥")
        key = normalize_fernet_key(raw_key)
        self._fernet = Fernet(key)
        return self._fernet


def normalize_fernet_key(raw_key: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(raw_key.encode("utf-8"))
        if len(decoded) == 32:
            return raw_key.encode("utf-8")
    except Exception:
        pass
    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class DevelopmentFernet:
    """Deterministic fallback used only in debug when cryptography is unavailable."""

    def __init__(self, key: bytes) -> None:
        self._key = key

    def encrypt(self, value: bytes) -> bytes:
        payload = bytes(
            byte ^ self._key[index % len(self._key)]
            for index, byte in enumerate(value)
        )
        return base64.urlsafe_b64encode(payload)

    def decrypt(self, token: bytes) -> bytes:
        payload = base64.urlsafe_b64decode(token)
        return bytes(byte ^ self._key[index % len(self._key)] for index, byte in enumerate(payload))


_secret_service: SecretService | None = None


def get_secret_service() -> SecretService:
    global _secret_service
    if _secret_service is None:
        _secret_service = SecretService()
    return _secret_service


def reset_secret_service() -> None:
    global _secret_service
    _secret_service = None
