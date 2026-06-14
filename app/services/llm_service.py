from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.config import get_settings


class LLMService:
    """统一 LLM 调用服务，通过 OpenAI 兼容接口接入各模型."""

    def __init__(self):
        self._settings = get_settings()
        self._clients: dict[str, ChatOpenAI] = {}

    def get_client(
        self,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0,
        streaming: bool = True,
    ) -> ChatOpenAI:
        provider = provider or self._settings.llm_provider
        model = model or self._settings.llm_model
        key = f"{provider}:{model}:{temperature}:{streaming}"

        if key not in self._clients:
            base_url, api_key = self._resolve_provider(provider)
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

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        client = self.get_client(**kwargs, streaming=False)
        resp = client.invoke(self._to_lc_messages(messages))
        return resp.content

    async def achat(self, messages: list[dict[str, str]], **kwargs) -> str:
        client = self.get_client(**kwargs, streaming=False)
        resp = await client.ainvoke(self._to_lc_messages(messages))
        return resp.content

    async def achat_stream(self, messages: list[dict[str, str]], **kwargs):
        client = self.get_client(**kwargs, streaming=True)
        async for chunk in client.astream(self._to_lc_messages(messages)):
            yield chunk

    async def achat_with_reasoning(
        self, messages: list[dict[str, str]], **kwargs
    ) -> tuple[str, str]:
        """返回 (content, reasoning_content). 捕获 MiMo 等推理模型的思考过程."""
        client = self.get_client(**kwargs, streaming=False)
        resp = await client.ainvoke(self._to_lc_messages(messages))
        content = resp.content or ""
        reasoning = ""
        # MiMo 返回 reasoning_content 在 additional_kwargs 中
        if hasattr(resp, "additional_kwargs"):
            reasoning = resp.additional_kwargs.get("reasoning_content", "")
        # 也检查 response_metadata
        if not reasoning and hasattr(resp, "response_metadata"):
            reasoning = resp.response_metadata.get("reasoning_content", "")
        return content, reasoning

    async def achat_stream_with_reasoning(
        self, messages: list[dict[str, str]], **kwargs
    ):
        """流式返回，yield (content_delta, reasoning_delta) 元组."""
        client = self.get_client(**kwargs, streaming=True)
        async for chunk in client.astream(self._to_lc_messages(messages)):
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
