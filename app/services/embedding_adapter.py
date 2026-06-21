"""Embedding provider adapter helpers.

The model registry stores a provider, base URL and model name, but vendors do
not all expose the exact same embedding endpoint shape.  Keep those differences
centralized here so model testing and real recall calls stay consistent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingRequestVariant:
    """One concrete endpoint/payload variant for an embedding request."""

    label: str
    url: str
    payload: dict[str, Any]


class EmbeddingProviderError(RuntimeError):
    """Raised when all embedding request variants fail."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_text: str | None = None,
        attempts: list[dict[str, Any]] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text or ""
        self.attempts = attempts or []


def build_embedding_request_variants(
    *,
    provider: str | None,
    base_url: str,
    model: str,
    text: str,
) -> list[EmbeddingRequestVariant]:
    """Build vendor-aware embedding request variants.

    Standard OpenAI-compatible providers use ``/embeddings`` with an array input.
    Volcengine Ark also exposes multimodal vectorization under
    ``/embeddings/multimodal``.  We try the standard endpoint first to preserve
    compatibility, then add the Ark-specific variant as a fallback.
    """

    normalized_base_url = base_url.rstrip("/")
    variants = [
        EmbeddingRequestVariant(
            label="openai_embeddings",
            url=f"{normalized_base_url}/embeddings",
            payload={"model": model, "input": [text], "encoding_format": "float"},
        )
    ]
    if is_volcengine_embedding_provider(provider, normalized_base_url, model):
        variants.append(
            EmbeddingRequestVariant(
                label="volcengine_multimodal_embeddings",
                url=f"{normalized_base_url}/embeddings/multimodal",
                payload={
                    "model": model,
                    "input": [{"type": "text", "text": text}],
                    "encoding_format": "float",
                },
            )
        )
    return variants


async def request_embedding(
    *,
    provider: str | None,
    base_url: str,
    model: str,
    text: str,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
) -> tuple[list[float], dict[str, Any]]:
    """Request an embedding and return ``(vector, metadata)``.

    Multiple request variants may be attempted for providers that need a vendor
    specific endpoint.  The returned metadata is safe to log and expose in test
    responses; it does not contain API keys or raw input text.
    """

    attempts: list[dict[str, Any]] = []
    variants = build_embedding_request_variants(
        provider=provider,
        base_url=base_url,
        model=model,
        text=text,
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        for variant in variants:
            try:
                response = await client.post(
                    variant.url,
                    json=variant.payload,
                    headers=headers or {},
                )
            except Exception as exc:
                attempts.append(
                    {
                        "variant": variant.label,
                        "url": variant.url,
                        "error": exc.__class__.__name__,
                        "detail": str(exc)[:200],
                    }
                )
                continue

            if response.status_code >= 400:
                attempts.append(
                    {
                        "variant": variant.label,
                        "url": variant.url,
                        "status_code": response.status_code,
                        "message": _compact_response(response.text),
                    }
                )
                if should_try_next_embedding_variant(response, variant, variants):
                    logger.info(
                        "embedding variant failed, trying next variant=%s status=%s",
                        variant.label,
                        response.status_code,
                    )
                    continue
                raise _embedding_error_from_attempts(attempts)

            data = response.json()
            vector = extract_embedding_vector(data)
            return vector, {
                "variant": variant.label,
                "url": variant.url,
                "attempts": attempts,
                "status_code": response.status_code,
            }

    raise _embedding_error_from_attempts(attempts)


def extract_embedding_vector(data: dict[str, Any]) -> list[float]:
    """Extract vector from OpenAI-compatible embedding response shapes."""

    items = data.get("data")
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict) and isinstance(first.get("embedding"), list):
            return first["embedding"]
    if isinstance(data.get("embedding"), list):
        return data["embedding"]
    raise EmbeddingProviderError("模型服务未返回有效向量")


def is_volcengine_embedding_provider(provider: str | None, base_url: str, model: str) -> bool:
    """Return whether a config should try Volcengine Ark embedding variants."""

    haystack = " ".join([provider or "", base_url or "", model or ""]).lower()
    return any(term in haystack for term in ("volc", "volces", "ark", "doubao", "豆包", "字节"))


def should_try_next_embedding_variant(
    response: httpx.Response,
    current: EmbeddingRequestVariant,
    variants: list[EmbeddingRequestVariant],
) -> bool:
    """Decide whether an embedding failure should fall through to a later variant."""

    if current is variants[-1]:
        return False
    if response.status_code in {400, 404, 405, 415, 422}:
        return True
    return False


def friendly_embedding_error_message(error: EmbeddingProviderError) -> str:
    """Return a user-facing summary for embedding connectivity errors."""

    last = error.attempts[-1] if error.attempts else {}
    message = str(last.get("message") or error.response_text or error)
    if "InvalidEndpointOrModel.NotFound" in message or "does not exist or you do not have access" in message:
        return (
            "模型或 endpoint 不存在，或当前 API Key 无权访问。"
            "请确认模型名称填写的是控制台/API Explorer 里的 Model ID 或 Endpoint ID；"
            "火山方舟向量化通常需要使用 /embeddings/multimodal。"
        )
    return message or "向量模型连接失败"


def _embedding_error_from_attempts(attempts: list[dict[str, Any]]) -> EmbeddingProviderError:
    last = attempts[-1] if attempts else {}
    return EmbeddingProviderError(
        str(last.get("message") or last.get("detail") or "向量模型连接失败"),
        status_code=last.get("status_code"),
        response_text=last.get("message") or last.get("detail") or "",
        attempts=attempts,
    )


def _compact_response(text: str) -> str:
    compact = " ".join((text or "").split())
    return compact[:500]
