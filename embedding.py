"""
BGE Embedding 模型共享实例

使用方式:
    # 新（推荐）: 构造器注入，可替换
    from services.config import AppConfig
    config = AppConfig.from_env()
    embedder = BGEEmbedder(config.embedding_model, config.embedding_device)
    vectors = embedder.encode(texts)

    # 旧（兼容）: 模块级单例函数
    from embedding import get_embedding_model
    model = get_embedding_model()
    vectors = model.encode(texts)
"""
from sentence_transformers import SentenceTransformer
from config import EMBEDDING_MODEL, EMBEDDING_DEVICE


class BGEEmbedder:
    """BGE 嵌入模型封装 — 可注入，可替换

    SentenceTransformer 的薄封装层。实例化即加载模型。
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL, device: str = EMBEDDING_DEVICE):
        self._model = SentenceTransformer(model_name, device=device)

    def encode(self, texts, **kwargs):
        """对文本列表生成向量嵌入。参数同 SentenceTransformer.encode()"""
        return self._model.encode(texts, **kwargs)

    @property
    def model(self):
        """底层 SentenceTransformer 实例（兼容直接访问）"""
        return self._model


# ============================================================================
# 兼容层 — 模块级单例（保留给旧代码）
# ============================================================================

_embedder: BGEEmbedder | None = None


def get_embedding_model() -> SentenceTransformer:
    """# Deprecated: 使用 BGEEmbedder 实例替代

    获取 BGE 模型全局单例。返回底层 SentenceTransformer 以保持向后兼容。
    """
    global _embedder
    if _embedder is None:
        _embedder = BGEEmbedder()
    return _embedder.model
