"""
DataPilot 配置中心 — 兼容层

旧代码（仍然有效）:
    from config import LLM_API_KEY, CHROMA_DIR

新代码（推荐）:
    from services.config import AppConfig
    config = AppConfig.from_env()
    service = YourService(config)

# Deprecated: 模块级变量是 AppConfig 的别名，保留到所有调用方迁移完毕
"""
from pathlib import Path

from services.config import AppConfig

# 初始化配置（副作用：HF_ENDPOINT + load_dotenv + mkdir）
_config = AppConfig.from_env(project_root=Path(__file__).resolve().parent)

# ── 兼容别名（旧代码无需修改） ──
PROJECT_ROOT = _config.project_root
DATA_DIR = _config.data_dir
CHROMA_DIR = _config.chroma_dir
DEMO_DIR = _config.demo_dir

LLM_API_KEY = _config.llm_api_key
LLM_BASE_URL = _config.llm_base_url
LLM_MODEL = _config.llm_model
LLM_TEMPERATURE = _config.llm_temperature
LLM_MAX_RETRY = _config.llm_max_retry

CHROMA_COLLECTION = _config.chroma_collection

EMBEDDING_MODEL = _config.embedding_model
EMBEDDING_DEVICE = _config.embedding_device

RETRIEVAL_LAYERS = list(_config.retrieval_layers)
RETRIEVAL_TOP_K = _config.retrieval_top_k
RETRIEVAL_THRESHOLD = _config.retrieval_threshold
