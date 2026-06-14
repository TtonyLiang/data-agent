import httpx

from app.config import get_settings


class EmbeddingService:
    """Embedding 服务，直接调用 Ollama OpenAI 兼容接口."""

    def __init__(self):
        s = get_settings()
        self._base_url = s.embedding_base_url.rstrip("/")
        self._model = s.embedding_model
        self._dimension = s.embedding_dimension

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            vec = await self.embed_query(text)
            results.append(vec)
        return results

    async def embed_query(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base_url}/embeddings",
                json={"model": self._model, "input": text},
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
