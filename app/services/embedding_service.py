import httpx

from app.config import get_settings
from app.services.model_config_service import get_model_config_service


class EmbeddingService:
    """Embedding 服务，直接调用 Ollama OpenAI 兼容接口."""

    def __init__(self):
        s = get_settings()
        self._base_url = s.embedding_base_url.rstrip("/")
        self._api_key = s.embedding_api_key
        self._model = s.embedding_model
        self._dimension = s.embedding_dimension

    async def embed_texts(self, texts: list[str], agent_id: int | None = None) -> list[list[float]]:
        results = []
        for text in texts:
            vec = await self.embed_query(text, agent_id=agent_id)
            results.append(vec)
        return results

    async def embed_query(self, text: str, agent_id: int | None = None) -> list[float]:
        base_url = self._base_url
        api_key = self._api_key
        model = self._model
        if agent_id:
            config = await get_model_config_service().get_agent_embedding_config(agent_id)
            if config is not None:
                base_url = config.base_url.rstrip("/")
                api_key = config.api_key if config.api_key_enabled else ""
                model = config.model_name
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base_url}/embeddings",
                json={"model": model, "input": text},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]

    def get_dimension(self) -> int:
        return self._dimension


_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
