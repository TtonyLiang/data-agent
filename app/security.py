"""安全中间件 —— Bearer 鉴权与进程内限流。

本模块在 FastAPI 层提供最小运行保护:
1. Bearer 鉴权:配置了 ADMIN_API_KEY 后,除 /health 外所有 /api/* 端点要求 Authorization 头。
2. 进程内限流:按 token/IP + 路径控制请求频率,滑动窗口算法。
3. 流式并发控制:chat_stream 端点额外限制同时运行的 stream 数。

限流策略:
- ``check_request``:滑动窗口,在 window_seconds 内最多允许 limit 次请求。
- ``acquire_session``:信号量,同时最多 max_concurrent 个活跃 session。
- 流式请求在 finally 中释放 session,保证异常时也能归还配额。
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.utils.logging_helpers import redact_text

logger = logging.getLogger(__name__)

# 公开端点(不要求鉴权)
PUBLIC_PATHS = {"/health"}


class InMemoryRateLimiter:
    """进程内限流器 —— 滑动窗口 + session 信号量。

    适用于开发和单进程部署。多进程部署时应使用 Redis 或其他分布式限流方案。
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._active_sessions: set[str] = set()

    def check_request(self, key: str, limit: int, window_seconds: int) -> bool:
        """滑动窗口限流:在 window_seconds 内最多允许 limit 次请求。

        返回 True 表示允许,False 表示应拒绝(返回 429)。
        """
        if limit <= 0:
            return True
        now = time.monotonic()
        hits = self._hits[key]
        # 清理窗口外的旧请求记录
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def acquire_session(self, session_key: str, max_concurrent: int) -> bool:
        """尝试获取一个活跃 session 配额(信号量语义)。

        返回 True 表示获取成功,False 表示已满或重复。
        """
        if max_concurrent <= 0:
            return True
        if session_key in self._active_sessions:
            return False
        if len(self._active_sessions) >= max_concurrent:
            return False
        self._active_sessions.add(session_key)
        return True

    def release_session(self, session_key: str) -> None:
        """释放活跃 session 配额。"""
        self._active_sessions.discard(session_key)


# 全局限流器实例
rate_limiter = InMemoryRateLimiter()


async def auth_and_rate_limit_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable],
):
    """FastAPI HTTP 中间件:Bearer 鉴权 + 路径级限流 + 流式并发控制。"""
    settings = get_settings()
    path = request.url.path

    # 公开端点跳过鉴权和限流
    if path in PUBLIC_PATHS:
        return await call_next(request)

    if path.startswith("/api/"):
        # Bearer 鉴权
        auth_error = validate_admin_authorization(request)
        if auth_error:
            return auth_error
        # 路径级限流(按 token 或 IP + 路径)
        limit_key = request.headers.get("authorization", "") or request.client.host
        if not rate_limiter.check_request(
            f"{limit_key}:{path}",
            settings.api_rate_limit_per_minute,
            60,
        ):
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试"},
            )

    # 流式并发控制
    session_key = ""
    is_chat_stream = path == "/api/chat/stream"
    if is_chat_stream and settings.chat_stream_max_concurrent > 0:
        session_key = build_stream_session_key(request)
        if not rate_limiter.acquire_session(
            session_key,
            settings.chat_stream_max_concurrent,
        ):
            return JSONResponse(
                status_code=429,
                content={"detail": "当前流式任务较多，请稍后再试"},
            )

    try:
        return await call_next(request)
    finally:
        # 流式请求完成或异常时释放配额
        if session_key:
            rate_limiter.release_session(session_key)


def validate_admin_authorization(request: Request) -> JSONResponse | None:
    """验证 Bearer token。返回 None 表示通过,返回 JSONResponse 表示拒绝。"""
    settings = get_settings()
    expected = (settings.admin_api_key or "").strip()

    if not expected:
        if not settings.debug:
            # 生产模式必须配置 ADMIN_API_KEY
            return JSONResponse(
                status_code=503,
                content={"detail": "服务未配置 ADMIN_API_KEY"},
            )
        # debug 模式无 key 时跳过鉴权
        return None

    authorization = request.headers.get("authorization", "")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return JSONResponse(status_code=401, content={"detail": "缺少访问令牌"})
    token = authorization[len(prefix) :].strip()
    if token != expected:
        # token 不匹配:记录脱敏后的 token 用于排查
        logger.warning(
            "admin auth failed path=%s token=%s",
            request.url.path,
            redact_text(token),
        )
        return JSONResponse(status_code=401, content={"detail": "访问令牌无效"})
    return None


def build_stream_session_key(request: Request) -> str:
    """构建流式请求的 session key(用于并发控制)。"""
    auth = request.headers.get("authorization", "")
    client = request.client.host if request.client else "unknown"
    return f"{auth or client}:chat-stream"
