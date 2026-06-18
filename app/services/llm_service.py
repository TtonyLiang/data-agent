import hashlib
import logging
import asyncio
import time

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.services.model_config_service import get_model_config_service

logger = logging.getLogger(__name__)


class LLMService:
    """统一 LLM 调用服务，通过 OpenAI 兼容接口接入各模型."""

    API_KEY_PLACEHOLDER = "not-needed"

    def __init__(self):
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
            self._clients[key] = ChatOpenAI(
                base_url=base_url,
                api_key=api_key,
                model=model,
                temperature=temperature,
                streaming=streaming,
            )
        return self._clients[key]

    def _resolve_provider(self, provider: str) -> tuple[str, str]:
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
        # OpenAI-compatible SDKs still require an api_key argument even when
        # local endpoints such as Ollama do not validate it.
        value = (api_key or "").strip()
        return value or self.API_KEY_PLACEHOLDER

    def _api_key_cache_token(self, api_key: str) -> str:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]

    def _messages_cache_key(self, messages: list[dict[str, str]], kwargs: dict) -> str:
        payload = {
            "messages": messages,
            "provider": kwargs.get("provider") or self._settings.llm_provider,
            "model": kwargs.get("model") or self._settings.llm_model,
            "base_url": kwargs.get("base_url") or "",
            "temperature": kwargs.get("temperature", 0),
        }
        return hashlib.sha256(
            repr(payload).encode("utf-8", errors="ignore")
        ).hexdigest()

    def _cache_get(self, key: str) -> str | None:
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
        if not agent_id:
            return {}
        config = await get_model_config_service().get_agent_chat_config(agent_id)
        if config is None:
            return {}
        return {
            "provider": config.provider,
            "model": config.model_name,
            "base_url": config.base_url,
            "api_key": config.api_key if config.api_key_enabled else None,
        }

    def _to_lc_messages(self, messages: list[dict[str, str]]) -> list:
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
        rendered = "\n".join(
            f"[{message.get('role', '')}] {message.get('content', '')}"
            for message in messages
        )
        rendered = truncate_text(rendered, self._settings.max_llm_prompt_log_chars)
        logger.info(
            "LLM request model=%s streaming=%s messages:\n%s",
            model or self._settings.llm_model,
            streaming,
            rendered,
        )

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        self.log_prompt_messages(
            messages,
            model=kwargs.get("model"),
            streaming=False,
        )
        cache_key = self._messages_cache_key(messages, kwargs)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.info("LLM cache hit model=%s", kwargs.get("model") or self._settings.llm_model)
            return cached
        client = self.get_client(**kwargs, streaming=False)
        resp = client.invoke(self._to_lc_messages(messages))
        content = str(resp.content or "")
        self._cache_put(cache_key, content)
        return content

    async def achat(self, messages: list[dict[str, str]], **kwargs) -> str:
        self.log_prompt_messages(
            messages,
            model=kwargs.get("model"),
            streaming=False,
        )
        cache_key = self._messages_cache_key(messages, kwargs)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.info("LLM cache hit model=%s", kwargs.get("model") or self._settings.llm_model)
            return cached
        client = self.get_client(**kwargs, streaming=False)
        lc_messages = self._to_lc_messages(messages)
        resp = await asyncio.to_thread(client.invoke, lc_messages)
        content = str(resp.content or "")
        self._cache_put(cache_key, content)
        return content

    async def achat_stream(self, messages: list[dict[str, str]], **kwargs):
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
                if chunk is not None:
                    yield chunk
        except Exception:
            async for chunk in client.astream(lc_messages):
                yield chunk

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
            logger.info("LLM cache hit with reasoning model=%s", kwargs.get("model") or self._settings.llm_model)
            try:
                content, reasoning = cached.split("\n---REASONING---\n", 1)
                return content, reasoning
            except ValueError:
                return cached, ""
        client = self.get_client(**kwargs, streaming=False)
        lc_messages = self._to_lc_messages(messages)
        resp = await asyncio.to_thread(client.invoke, lc_messages)
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
        return content, reasoning

    async def achat_stream_with_reasoning(
        self, messages: list[dict[str, str]], **kwargs
    ):
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
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


def truncate_text(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"
