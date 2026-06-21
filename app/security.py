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

PUBLIC_PATHS = {"/health"}


class InMemoryRateLimiter:
    """Small process-local limiter for development and single-process deployments."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._active_sessions: set[str] = set()

    def check_request(self, key: str, limit: int, window_seconds: int) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def acquire_session(self, session_key: str, max_concurrent: int) -> bool:
        if max_concurrent <= 0:
            return True
        if session_key in self._active_sessions:
            return False
        if len(self._active_sessions) >= max_concurrent:
            return False
        self._active_sessions.add(session_key)
        return True

    def release_session(self, session_key: str) -> None:
        self._active_sessions.discard(session_key)


rate_limiter = InMemoryRateLimiter()


async def auth_and_rate_limit_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable],
):
    settings = get_settings()
    path = request.url.path
    if path in PUBLIC_PATHS:
        return await call_next(request)

    if path.startswith("/api/"):
        auth_error = validate_admin_authorization(request)
        if auth_error:
            return auth_error
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
        if session_key:
            rate_limiter.release_session(session_key)


def validate_admin_authorization(request: Request) -> JSONResponse | None:
    settings = get_settings()
    expected = (settings.admin_api_key or "").strip()
    if not expected:
        if not settings.debug:
            return JSONResponse(
                status_code=503,
                content={"detail": "服务未配置 ADMIN_API_KEY"},
            )
        return None

    authorization = request.headers.get("authorization", "")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return JSONResponse(status_code=401, content={"detail": "缺少访问令牌"})
    token = authorization[len(prefix) :].strip()
    if token != expected:
        logger.warning(
            "admin auth failed path=%s token=%s",
            request.url.path,
            redact_text(token),
        )
        return JSONResponse(status_code=401, content={"detail": "访问令牌无效"})
    return None


def build_stream_session_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    client = request.client.host if request.client else "unknown"
    return f"{auth or client}:chat-stream"
