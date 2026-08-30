"""LLM 统一调用服务 —— 通过 OpenAI 兼容接口接入各模型。

LLMService 是所有节点调用大语言模型的统一入口,负责:
1. 客户端管理:按 (provider, model, base_url, temperature, streaming) 缓存 ChatOpenAI 实例。
2. 响应缓存:可选的进程内 LLM 响应缓存,减少重复调用(见 llm_cache_enabled 配置)。
3. 日志记录:每次请求/响应都记录 prompt 组成、模型名、token 数、缓存命中等。
4. 多种调用模式:
   - ``chat``/``achat``:同步/异步非流式,返回完整文本。
   - ``achat_stream``:异步流式,逐 chunk yield。
   - ``achat_with_reasoning``:异步非流式 + reasoning_content 提取(适配 MiMo 等推理模型)。
   - ``achat_stream_with_reasoning``:异步流式 + reasoning 提取。

``resolve_agent_chat_kwargs`` 根据 agent_id 解析绑定的模型配置,
无绑定时回退到环境默认配置(LLM_MODEL / LLM_BASE_URL 等)。
"""

import hashlib
import logging
import time

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.services.model_config_service import get_model_config_service
from app.utils.logging_helpers import (
    json_for_log,
)
from app.utils.logging_helpers import (
    truncate_text as safe_truncate_text,
)
from app.utils.openai_compat import normalize_openai_base_url

logger = logging.getLogger(__name__)


class LLMResponseError(RuntimeError):
    """模型服务返回内容或调用结果不符合当前客户端约定。"""


class LLMService:
    """统一 LLM 调用服务,通过 OpenAI 兼容接口接入各模型。"""

    # 本地兼容端点(如 Ollama)不需要真实 API Key,用此占位值
    API_KEY_PLACEHOLDER = "not-needed"

    def __init__(self):
        """初始化模型客户端缓存和响应缓存。"""
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
        """返回缓存的 OpenAI 兼容客户端。

        缓存键由 (provider, base_url, model, temperature, streaming, api_key_digest) 组成,
        相同参数复用同一客户端实例,避免重复创建连接。
        """
        provider = provider or self._settings.llm_provider
        model = model or self._settings.llm_model
        if not base_url:
            base_url, api_key = self._resolve_provider(provider)
        base_url = normalize_openai_base_url(base_url)
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
        """根据供应商名称解析 base_url 和 api_key。

        当前所有供应商共用环境变量中的 llm_base_url/llm_api_key,
        通过 provider 字段区分(实际 API 调用不依赖此值)。
        """
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
        """确保 api_key 非空:本地兼容端点(如 Ollama)不校验 Key,但 SDK 要求非空。"""
        value = (api_key or "").strip()
        return value or self.API_KEY_PLACEHOLDER

    @staticmethod
    def _content_text(message) -> str:
        """把 LangChain 文本或内容块统一为字符串。"""
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    value = block.get("text") or block.get("content") or ""
                else:
                    value = block
                if value:
                    parts.append(str(value))
            return "".join(parts)
        return str(content or "")

    def _format_call_error(self, exc: Exception, kwargs: dict) -> LLMResponseError:
        """将 SDK 的低层异常转换为可操作的配置提示。"""
        if isinstance(exc, LLMResponseError):
            return exc
        detail = safe_truncate_text(str(exc or "").strip(), 320)
        model = kwargs.get("model") or getattr(self._settings, "llm_model", "") or "未指定"
        lowered = detail.lower()
        if "no generation chunks" in lowered:
            message = (
                f"大模型未返回有效生成内容（模型 {model}）。"
                "请检查 Base URL 是否包含 /v1、模型名称是否可用，以及服务是否支持流式输出。"
            )
        elif "model_dump" in lowered or "html" in lowered:
            message = (
                f"大模型返回了非 OpenAI 兼容格式（模型 {model}）。"
                "请检查 Base URL 是否指向 /v1/chat/completions，而不是网页地址。"
            )
        else:
            message = (
                f"大模型调用失败（模型 {model}）。"
                "请检查 Base URL、模型名称、API Key 和上游服务状态。"
            )
        if detail:
            message = f"{message} 原始错误：{detail}"
        return LLMResponseError(message)

    @staticmethod
    def _can_retry_stream(exc: Exception) -> bool:
        """只对流式协议不兼容或空分块重试，避免重复发送鉴权/网络错误。"""
        detail = str(exc or "").lower()
        return (
            "no generation chunks" in detail
            or isinstance(exc, (TypeError, AttributeError))
        )

    def _api_key_cache_token(self, api_key: str) -> str:
        """返回 api_key 的短摘要(非密文),用于缓存键和诊断日志。"""
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]

    def _messages_cache_key(self, messages: list[dict[str, str]], kwargs: dict) -> str:
        """构建请求级别的缓存键(消息内容 + 模型参数),用于响应缓存匹配。"""
        payload = {
            "messages": messages,
            "provider": kwargs.get("provider")
            or getattr(self._settings, "llm_provider", ""),
            "model": kwargs.get("model")
            or getattr(self._settings, "llm_model", ""),
            "base_url": kwargs.get("base_url") or "",
            "temperature": kwargs.get("temperature", 0),
        }
        return hashlib.sha256(repr(payload).encode("utf-8", errors="ignore")).hexdigest()

    def _cache_get(self, key: str) -> str | None:
        """从响应缓存取值,过期或未启用时返回 None。"""
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
        """写入响应缓存,超限时淘汰最旧条目。"""
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
        """解析 agent 绑定的模型配置,转为 get_client 需要的 kwargs。

        无 agent_id 或无绑定配置时返回空 dict(走环境默认值)。
        """
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
        """把 role/content 字典列表转为 LangChain 消息对象列表。"""
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
        """记录 prompt 请求日志(消息组成 + 详细内容预览)。"""
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
        # 详细日志模式下记录完整 prompt 内容
        if getattr(
            self._settings,
            "detailed_data_logging_enabled",
            False,
        ) and getattr(self._settings, "llm_prompt_logging_enabled", True):
            rendered = "\n".join(
                f"[{message.get('role', '')}] {message.get('content', '')}" for message in messages
            )
            rendered = safe_truncate_text(rendered, self._settings.max_llm_prompt_log_chars)
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
        """记录响应日志(content 长度 + reasoning 长度 + 详细预览)。"""
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
                safe_truncate_text(
                    content,
                    getattr(self._settings, "max_llm_prompt_log_chars", 8000),
                ),
                safe_truncate_text(
                    reasoning,
                    getattr(self._settings, "max_reasoning_trace_chars", 12000),
                ),
            )

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """同步调用 chat 模型,返回完整文本。"""
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
        try:
            resp = client.invoke(self._to_lc_messages(messages))
            content = self._content_text(resp)
            if not content.strip():
                raise LLMResponseError("大模型返回空内容，请检查模型名称和服务状态。")
        except Exception as exc:
            raise self._format_call_error(exc, kwargs) from exc
        self._cache_put(cache_key, content)
        self.log_response_text(content, model=kwargs.get("model"))
        return content

    async def achat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """异步调用 chat 模型,返回完整文本。"""
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
        try:
            resp = await client.ainvoke(lc_messages)
            content = self._content_text(resp)
            if not content.strip():
                raise LLMResponseError("大模型返回空内容，请检查模型名称和服务状态。")
        except Exception as exc:
            raise self._format_call_error(exc, kwargs) from exc
        self._cache_put(cache_key, content)
        self.log_response_text(content, model=kwargs.get("model"))
        return content

    async def achat_stream(self, messages: list[dict[str, str]], **kwargs):
        """异步流式调用,逐 chunk yield。

        实现策略:
        1. 优先用 astream_events(version='v2') 获取结构化事件流,
           从中提取 on_chat_model_stream 事件的 chunk。
        2. 如果 astream_events 失败(如 API 不兼容),回退到 astream。
        3. 两种流式方式都没有内容时,回退到同配置的非流式请求。
        4. 全程记录 chunk 数和 content 总字符数。
        """
        self.log_prompt_messages(
            messages,
            model=kwargs.get("model"),
            streaming=True,
        )
        client = self.get_client(**kwargs, streaming=True)
        lc_messages = self._to_lc_messages(messages)
        content_chars = 0
        chunk_count = 0
        streamed_any = False
        has_output = False
        stream_error: Exception | None = None
        try:
            try:
                # 优先用 astream_events:支持 reasoning 等结构化事件
                async for event in client.astream_events(lc_messages, version="v2"):
                    if event.get("event") != "on_chat_model_stream":
                        continue
                    chunk = event.get("data", {}).get("chunk")
                    if chunk is not None:
                        streamed_any = True
                        chunk_text = self._content_text(chunk)
                        additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
                        reasoning = additional_kwargs.get("reasoning_content", "")
                        has_output = has_output or bool(chunk_text or reasoning)
                        chunk_count += 1
                        content_chars += len(chunk_text)
                        yield chunk
            except Exception as exc:
                stream_error = exc
                # 已经向调用方交付过分块后再失败，不能重新请求并拼接重复内容。
                if streamed_any or not self._can_retry_stream(exc):
                    raise self._format_call_error(exc, kwargs) from exc

            if not streamed_any:
                try:
                    async for chunk in client.astream(lc_messages):
                        streamed_any = True
                        chunk_text = self._content_text(chunk)
                        additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
                        reasoning = additional_kwargs.get("reasoning_content", "")
                        has_output = has_output or bool(chunk_text or reasoning)
                        chunk_count += 1
                        content_chars += len(chunk_text)
                        yield chunk
                except Exception as exc:
                    stream_error = exc
                    if streamed_any or not self._can_retry_stream(exc):
                        raise self._format_call_error(exc, kwargs) from exc

            # 某些 OpenAI 兼容端点接受 stream=true 但返回空响应,用普通请求兜底。
            if not has_output:
                logger.warning(
                    "LLM stream empty; falling back to non-streaming model=%s",
                    kwargs.get("model") or self._settings.llm_model,
                )
                fallback_client = self.get_client(**kwargs, streaming=False)
                try:
                    response = await fallback_client.ainvoke(lc_messages)
                    content = self._content_text(response)
                except Exception as exc:
                    raise self._format_call_error(exc, kwargs) from exc
                if not content.strip():
                    cause = stream_error or LLMResponseError("大模型返回空内容。")
                    raise self._format_call_error(cause, kwargs) from cause
                streamed_any = True
                has_output = True
                chunk_count = 1
                content_chars = len(content)
                yield AIMessageChunk(content=content)
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
        """异步调用并返回 (content, reasoning_content)。

        适配 MiMo 等推理模型:reasoning_content 可能在:
        - resp.additional_kwargs.reasoning_content
        - resp.response_metadata.reasoning_content
        两个位置,按顺序尝试提取。
        """
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
        try:
            resp = await client.ainvoke(lc_messages)
            content = self._content_text(resp)
            if not content.strip():
                raise LLMResponseError("大模型返回空内容，请检查模型名称和服务状态。")
        except Exception as exc:
            raise self._format_call_error(exc, kwargs) from exc

        # MiMo 推理模型适配:reasoning_content 在 additional_kwargs 或 response_metadata 中
        reasoning = ""
        if hasattr(resp, "additional_kwargs"):
            reasoning = resp.additional_kwargs.get("reasoning_content", "")
        if not reasoning and hasattr(resp, "response_metadata"):
            reasoning = resp.response_metadata.get("reasoning_content", "")

        reasoning = safe_truncate_text(
            str(reasoning or ""), self._settings.max_reasoning_trace_chars
        )
        # 缓存时把 content 和 reasoning 拼接,用分隔符隔开
        self._cache_put(cache_key, f"{content}\n---REASONING---\n{reasoning}")
        self.log_response_text(content, model=kwargs.get("model"), reasoning=reasoning)
        return content, reasoning

    async def achat_stream_with_reasoning(self, messages: list[dict[str, str]], **kwargs):
        """异步流式调用,逐 chunk yield (content_delta, reasoning_delta) 元组。

        用于需要同时转发 content 和 reasoning 流的节点(如 semantic_enhance)。
        """
        async for chunk in self.achat_stream(messages, **kwargs):
            content = self._content_text(chunk)
            additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
            reasoning = additional_kwargs.get("reasoning_content", "")
            yield content, reasoning


# 全局单例
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """返回进程级 LLM 服务单例。"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


def truncate_text(text: str, limit: int) -> str:
    """向后兼容的截断函数,实际委托给 logging_helpers。"""
    return safe_truncate_text(text, limit)
