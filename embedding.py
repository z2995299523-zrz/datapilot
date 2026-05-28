"""
BGE Embedding 模型共享单例

indexer.py 和 matcher.py 共用同一个模型实例，避免重复加载 100MB BGE 模型。
"""
from sentence_transformers import SentenceTransformer
from config import EMBEDDING_MODEL, EMBEDDING_DEVICE

_model: SentenceTransformer | None = None


def get_embedding_model() -> SentenceTransformer:
    """获取 BGE 模型全局单例"""
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL, device=EMBEDDING_DEVICE)
    return _model
