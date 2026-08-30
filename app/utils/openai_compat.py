"""Helpers for OpenAI-compatible endpoint configuration."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def normalize_openai_base_url(base_url: str | None) -> str:
    """Normalize an OpenAI-compatible API base URL.

    OpenAI-compatible SDKs append ``/chat/completions`` or ``/embeddings`` to
    the configured base URL.  A host-only URL therefore needs the conventional
    ``/v1`` prefix, while an explicitly configured path must be preserved.
    Empty values stay empty so callers can report a missing configuration.
    """
    value = str(base_url or "").strip()
    if not value:
        return ""

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        # Leave malformed values untouched so the caller can report a useful
        # connection error instead of manufacturing another invalid URL.
        return value.rstrip("/")
    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1"

    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))
