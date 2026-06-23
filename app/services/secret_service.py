"""密钥加解密服务 —— 数据源密码与 API Key 的加密落盘与解密读取。

SecretService 使用 Fernet 对称加密,所有密钥以 ``enc:v1:`` 前缀 + 密文存储。

加解密流程:
- ``encrypt``:明文 → Fernet 加密 → 拼接 ``enc:v1:`` 前缀。
- ``decrypt``:去掉前缀 → Fernet 解密 → 明文。
- 已加密的值(有 ``enc:v1:`` 前缀)再次 encrypt 时原样返回(幂等)。

密钥来源:
1. 优先使用环境变量 SECRET_ENCRYPTION_KEY。
2. debug 模式下缺省时使用 DevelopmentFernet(XOR 弱加密,仅开发用)。

降级说明:
当 cryptography 库未安装且处于 debug 模式时,自动降级到 DevelopmentFernet。
此时会记录 warning 日志,提示这是弱加密仅用于开发。
"""

from __future__ import annotations

import base64
import hashlib
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

# 加密值前缀标识:所有加密落盘的值都以此开头
ENCRYPTED_PREFIX = "enc:v1:"


class SecretServiceError(RuntimeError):
    """密钥服务异常。"""


class SecretService:
    """密钥加解密服务。"""

    def __init__(self) -> None:
        self._fernet = None

    def encrypt(self, value: str | None) -> str | None:
        """加密明文值,已加密的值原样返回(幂等)。"""
        if value is None:
            return None
        if value.startswith(ENCRYPTED_PREFIX):
            # 已加密,原样返回
            return value
        if value == "":
            return value
        encrypted = ENCRYPTED_PREFIX + self._get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")
        logger.info("secret encrypt ok value_chars=%s", len(value or ""))
        return encrypted

    def decrypt(self, value: str | None) -> str | None:
        """解密加密值,非加密值原样返回(兼容旧明文数据)。"""
        if value is None:
            return None
        if not value.startswith(ENCRYPTED_PREFIX):
            # 非加密值(旧数据),原样返回
            return value
        token = value[len(ENCRYPTED_PREFIX) :].encode("utf-8")
        try:
            decrypted = self._get_fernet().decrypt(token).decode("utf-8")
            logger.info("secret decrypt ok")
            return decrypted
        except Exception as exc:
            logger.exception("secret decrypt FAILED")
            raise SecretServiceError("密钥解密失败，请检查 SECRET_ENCRYPTION_KEY") from exc

    def _get_fernet(self):
        """获取或初始化 Fernet 实例。debug 模式下缺省时降级到 DevelopmentFernet。"""
        if self._fernet is not None:
            return self._fernet
        settings = get_settings()
        raw_key = (settings.secret_encryption_key or "").strip()

        if not raw_key and settings.debug:
            import secrets
            raw_key = secrets.token_hex(32)
            logger.warning("secret using randomly generated key (DEBUG mode only, changes on restart)")

        try:
            from cryptography.fernet import Fernet
        except ModuleNotFoundError as exc:
            if settings.debug:
                # 降级:debug 模式且 cryptography 未安装时,使用 DevelopmentFernet
                logger.warning(
                    "secret cryptography not available, falling back to DevelopmentFernet "
                    "(WEAK encryption, DEBUG mode only)"
                )
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
    """把任意字符串转为合法的 Fernet key(base64 编码的 32 字节)。

    先尝试直接解码(若已经是合法 Fernet key);否则对原始字符串做 SHA256 哈希后再编码。
    """
    try:
        decoded = base64.urlsafe_b64decode(raw_key.encode("utf-8"))
        if len(decoded) == 32:
            return raw_key.encode("utf-8")
    except Exception:
        pass
    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class DevelopmentFernet:
    """开发模式弱加密 —— 仅用于 debug 模式下 cryptography 未安装时的降级方案。

    使用 XOR 加密,安全性远低于 Fernet,生产环境必须安装 cryptography。
    """

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


# 全局单例
_secret_service: SecretService | None = None


def get_secret_service() -> SecretService:
    """返回进程级密钥服务单例。"""
    global _secret_service
    if _secret_service is None:
        _secret_service = SecretService()
    return _secret_service


def reset_secret_service() -> None:
    """重置单例(测试用)。"""
    global _secret_service
    _secret_service = None
