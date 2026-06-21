"""文本分块工具 —— 按固定大小切分文本,支持重叠窗口。

用于知识文档向量化前的预处理,把长文本切成适合 embedding 的小块。
"""


def split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """按固定大小切分文本,支持重叠窗口。

    参数:
        text:待切分文本
        chunk_size:每个块的最大字符数(默认 500)
        chunk_overlap:相邻块的重叠字符数(默认 50),
            重叠保证边界处的语义不会被切断

    返回:
        分块后的字符串列表。文本长度不超过 chunk_size 时直接返回原文。

    算法:滑动窗口,步长为 chunk_size - chunk_overlap。
    例如 chunk_size=10, chunk_overlap=3 时:
    [0:10], [7:17], [14:24], ... 直到覆盖全文。
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        # 步长 = chunk_size - chunk_overlap,实现重叠
        start = end - chunk_overlap
    return chunks
