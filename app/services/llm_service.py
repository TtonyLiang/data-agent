import hashlib
import logging
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.services.model_config_service import get_model_config_service
from app.utils.logging_helpers import (
    json_for_log,
)
from app.utils.logging_helpers import (
    truncate_text as safe_truncate_text,
)

logger = logging.getLogger(__name__)


class LLMService:
    """统一 LLM 调用服务，通过 OpenAI 兼容接口接入各模型."""

    API_KEY_PLACEHOLDER = "not-needed"

    def __init__(self):
        """Initialize model client and response caches for this process."""
        self._settings = get_settings()
        self._clients: dict[str, ChatOpenAI] = {}
        self._response_cache: dict[str, tuple[float, str]] = {}

    def get_client(
        self,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0,
        streaming: bool = True,
    ) -> ChatOpenAI:
        """Return a cached OpenAI-compatible client for the resolved model settings."""
        provider = provider or self._settings.llm_provider
        model = model or self._settings.llm_model
        if not base_url:
            base_url, api_key = self._resolve_provider(provider)
        api_key = self._normalize_api_key(api_key)
        key = (
            f"{provider}:{base_url or ''}:{model}:{temperature}:{streaming}:"
            f"{self._api_key_cache_token(api_key)}"
        )

        if key not in self._clients:
            logger.info(
                "LLM client create provider=%s base_url=%s model=%s "
                "temperature=%s streaming=%s api_key_token=%s",
                provider,
                base_url,
                model,
                temperature,
                streaming,
                self._api_key_cache_token(api_key),
            )
            self._clients[key] = ChatOpenAI(
                base_url=base_url,
                api_key=api_key,
                model=model,
                temperature=temperature,
                streaming=streaming,
            )
        return self._clients[key]

    def _resolve_provider(self, provider: str) -> tuple[str, str]:
        """Resolve base URL and API key from the configured provider name."""
        s = self._settings
        providers = {
            "deepseek": (s.llm_base_url, s.llm_api_key),
            "mimo": (s.llm_base_url, s.llm_api_key),
            "minimax": (s.llm_base_url, s.llm_api_key),
            "ollama": (s.llm_base_url, s.llm_api_key),
        }
        if provider in providers:
            return providers[provider]
        return s.llm_base_url, s.llm_api_key

    def _normalize_api_key(self, api_key: str | None) -> str:
        """Supply a placeholder key when a local compatible endpoint accepts keyless calls."""
        # OpenAI-compatible SDKs still require an api_key argument even when
        # local endpoints such as Ollama do not validate it.
        value = (api_key or "").strip()
        return value or self.API_KEY_PLACEHOLDER

    def _api_key_cache_token(self, api_key: str) -> str:
        """Return a short non-secret digest for client cache keys and diagnostics."""
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]

    def _messages_cache_key(self, messages: list[dict[str, str]], kwargs: dict) -> str:
        """Build a deterministic cache key from messages plus model selection parameters."""
        payload = {
            "messages": messages,
            "provider": kwargs.get("provider") or self._settings.llm_provider,
            "model": kwargs.get("model") or self._settings.llm_model,
            "base_url": kwargs.get("base_url") or "",
            "temperature": kwargs.get("temperature", 0),
        }
        return hashlib.sha256(repr(payload).encode("utf-8", errors="ignore")).hexdigest()

    def _cache_get(self, key: str) -> str | None:
        """Return a cached response if caching is enabled and the entry has not expired."""
        if not self._settings.llm_cache_enabled:
            return None
        cached = self._response_cache.get(key)
        if not cached:
            return None
        created_at, value = cached
        if time.monotonic() - created_at > self._settings.llm_cache_ttl_seconds:
            self._response_cache.pop(key, None)
            return None
        return value

    def _cache_put(self, key: str, value: str) -> None:
        """Store a response in the bounded in-memory LLM response cache."""
        if not self._settings.llm_cache_enabled:
            return
        if len(self._response_cache) >= self._settings.llm_cache_max_items:
            oldest_key = min(
                self._response_cache,
                key=lambda item: self._response_cache[item][0],
            )
            self._response_cache.pop(oldest_key, None)
        self._response_cache[key] = (time.monotonic(), value)

    async def resolve_agent_chat_kwargs(self, agent_id: int | None) -> dict:
        """Resolve per-agent chat-model configuration into keyword arguments for calls."""
        if not agent_id:
            logger.info("LLM config resolve skipped: no agent_id, using defaults")
            return {}
        config = await get_model_config_service().get_agent_chat_config(agent_id)
        if config is None:
            logger.info("LLM config resolve agent_id=%s result=default", agent_id)
            return {}
        kwargs = {
            "provider": config.provider,
            "model": config.model_name,
            "base_url": config.base_url,
            "api_key": config.api_key if config.api_key_enabled else None,
        }
        logger.info(
            "LLM config resolve agent_id=%s result=%s",
            agent_id,
            json_for_log({**kwargs, "api_key_enabled": config.api_key_enabled}),
        )
        return kwargs

    def _to_lc_messages(self, messages: list[dict[str, str]]) -> list:
        """Convert role/content dictionaries into LangChain message instances."""
        lc_messages = []
        for m in messages:
            if m["role"] == "system":
                lc_messages.append(SystemMessage(content=m["content"]))
            elif m["role"] == "user":
                lc_messages.append(HumanMessage(content=m["content"]))
            elif m["role"] == "assistant":
                lc_messages.append(AIMessage(content=m["content"]))
        return lc_messages

    def log_prompt_messages(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        streaming: bool = False,
    ) -> None:
        """Log prompt messages exactly as sent to the model, with configured truncation."""
        message_summary = [
            {
                "role": message.get("role", ""),
                "chars": len(message.get("content", "") or ""),
            }
            for message in messages
        ]
        logger.info(
            "LLM request model=%s streaming=%s message_count=%s message_summary=%s",
            model or self._settings.llm_model,
            streaming,
            len(messages),
            json_for_log(message_summary),
        )
        if getattr(
            self._settings,
            "detailed_data_logging_enabled",
            False,
        ) and getattr(self._settings, "llm_prompt_logging_enabled", True):
            rendered = "\n".join(
                f"[{message.get('role', '')}] {message.get('content', '')}" for message in messages
            )
            rendered = truncate_text(rendered, self._settings.max_llm_prompt_log_chars)
            logger.info(
                "LLM request preview model=%s messages:\n%s",
                model or self._settings.llm_model,
                rendered,
            )

    def log_response_text(
        self,
        content: str,
        *,
        model: str | None = None,
        streaming: bool = False,
        cache_hit: bool = False,
        reasoning: str = "",
    ) -> None:
        """Log a bounded preview of model output and reasoning output."""
        logger.info(
            "LLM response model=%s streaming=%s cache_hit=%s content_chars=%s reasoning_chars=%s",
            model or self._settings.llm_model,
            streaming,
            cache_hit,
            len(content or ""),
            len(reasoning or ""),
        )
        if getattr(self._settings, "detailed_data_logging_enabled", False):
            logger.info(
                "LLM response preview model=%s content=%s reasoning=%s",
                model or self._settings.llm_model,
                truncate_text(content, getattr(self._settings, "max_llm_prompt_log_chars", 8000)),
                truncate_text(
                    reasoning,
                    getattr(self._settings, "max_reasoning_trace_chars", 12000),
                ),
            )

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """Synchronously invoke a chat model and return text content."""
        self.log_prompt_messages(
            messages,
            model=kwargs.get("model"),
            streaming=False,
        )
        cache_key = self._messages_cache_key(messages, kwargs)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.info("LLM cache hit model=%s", kwargs.get("model") or self._settings.llm_model)
            self.log_response_text(cached, model=kwargs.get("model"), cache_hit=True)
            return cached
        client = self.get_client(**kwargs, streaming=False)
        resp = client.invoke(self._to_lc_messages(messages))
        content = str(resp.content or "")
        self._cache_put(cache_key, content)
        self.log_response_text(content, model=kwargs.get("model"))
        return content

    async def achat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """Invoke a chat model from async code without blocking the event loop."""
        self.log_prompt_messages(
            messages,
            model=kwargs.get("model"),
            streaming=False,
        )
        cache_key = self._messages_cache_key(messages, kwargs)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.info("LLM cache hit model=%s", kwargs.get("model") or self._settings.llm_model)
            self.log_response_text(cached, model=kwargs.get("model"), cache_hit=True)
            return cached
        client = self.get_client(**kwargs, streaming=False)
        lc_messages = self._to_lc_messages(messages)
        resp = await client.ainvoke(lc_messages)
        content = str(resp.content or "")
        self._cache_put(cache_key, content)
        self.log_response_text(content, model=kwargs.get("model"))
        return content

    async def achat_stream(self, messages: list[dict[str, str]], **kwargs):
        """Yield streaming chat chunks, using a fallback stream API when event streaming fails."""
        self.log_prompt_messages(
            messages,
            model=kwargs.get("model"),
            streaming=True,
        )
        client = self.get_client(**kwargs, streaming=True)
        lc_messages = self._to_lc_messages(messages)
        content_chars = 0
        chunk_count = 0
        try:
            async for event in client.astream_events(lc_messages, version="v2"):
                if event.get("event") != "on_chat_model_stream":
                    continue
                chunk = event.get("data", {}).get("chunk")
                if chunk is not None:
                    chunk_count += 1
                    content_chars += len(str(getattr(chunk, "content", "") or ""))
                    yield chunk
        except Exception:
            async for chunk in client.astream(lc_messages):
                chunk_count += 1
                content_chars += len(str(getattr(chunk, "content", "") or ""))
                yield chunk
        finally:
            logger.info(
                "LLM stream finished model=%s chunks=%s content_chars=%s",
                kwargs.get("model") or self._settings.llm_model,
                chunk_count,
                content_chars,
            )

    async def achat_with_reasoning(
        self, messages: list[dict[str, str]], **kwargs
    ) -> tuple[str, str]:
        """返回 (content, reasoning_content). 捕获 MiMo 等推理模型的思考过程."""
        self.log_prompt_messages(
            messages,
            model=kwargs.get("model"),
            streaming=False,
        )
        cache_key = self._messages_cache_key(messages, {**kwargs, "_reasoning": True})
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.info(
                "LLM cache hit with reasoning model=%s",
                kwargs.get("model") or self._settings.llm_model,
            )
            try:
                content, reasoning = cached.split("\n---REASONING---\n", 1)
                self.log_response_text(
                    content,
                    model=kwargs.get("model"),
                    cache_hit=True,
                    reasoning=reasoning,
                )
                return content, reasoning
            except ValueError:
                self.log_response_text(cached, model=kwargs.get("model"), cache_hit=True)
                return cached, ""
        client = self.get_client(**kwargs, streaming=False)
        lc_messages = self._to_lc_messages(messages)
        resp = await client.ainvoke(lc_messages)
        content = str(resp.content or "")
        reasoning = ""
        # MiMo 返回 reasoning_content 在 additional_kwargs 中
        if hasattr(resp, "additional_kwargs"):
            reasoning = resp.additional_kwargs.get("reasoning_content", "")
        # 也检查 response_metadata
        if not reasoning and hasattr(resp, "response_metadata"):
            reasoning = resp.response_metadata.get("reasoning_content", "")
        reasoning = truncate_text(str(reasoning or ""), self._settings.max_reasoning_trace_chars)
        self._cache_put(cache_key, f"{content}\n---REASONING---\n{reasoning}")
        self.log_response_text(content, model=kwargs.get("model"), reasoning=reasoning)
        return content, reasoning

    async def achat_stream_with_reasoning(self, messages: list[dict[str, str]], **kwargs):
        """流式返回，yield (content_delta, reasoning_delta) 元组."""
        self.log_prompt_messages(
            messages,
            model=kwargs.get("model"),
            streaming=True,
        )
        client = self.get_client(**kwargs, streaming=True)
        lc_messages = self._to_lc_messages(messages)
        try:
            async for event in client.astream_events(lc_messages, version="v2"):
                if event.get("event") != "on_chat_model_stream":
                    continue
                chunk = event.get("data", {}).get("chunk")
                if chunk is None:
                    continue
                content = chunk.content or ""
                reasoning = ""
                if hasattr(chunk, "additional_kwargs"):
                    reasoning = chunk.additional_kwargs.get("reasoning_content", "")
                yield content, reasoning
        except Exception:
            async for chunk in client.astream(lc_messages):
                content = chunk.content or ""
                reasoning = ""
                if hasattr(chunk, "additional_kwargs"):
                    reasoning = chunk.additional_kwargs.get("reasoning_content", "")
                yield content, reasoning


_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Return the process-wide LLM service singleton."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


def truncate_text(text: str, limit: int) -> str:
    """Compatibility wrapper for older imports that expect truncation in this module."""
    return safe_truncate_text(text, limit)
