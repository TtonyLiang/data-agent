def split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """简单文本分块."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - chunk_overlap
    return chunks
