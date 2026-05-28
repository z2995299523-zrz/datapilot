"""
DataPilot 配置中心

DeepSeek / ChromaDB / BGE Embedding / 项目路径
"""
import os
from pathlib import Path

# ============================================================================
# HF 镜像 — 必须在 HuggingFace 任何加载之前设置
# ============================================================================
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# ============================================================================
# .env 加载 — 必须在 os.getenv 之前
# ============================================================================
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# ============================================================================
# 项目路径
# ============================================================================
DATA_DIR = PROJECT_ROOT / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"
DEMO_DIR = PROJECT_ROOT / "demo"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# DeepSeek (OpenAI 兼容)
# ============================================================================
LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your-deepseek-api-key")
LLM_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
LLM_TEMPERATURE = 0.1
LLM_MAX_RETRY = 3

# ============================================================================
# ChromaDB
# ============================================================================
CHROMA_COLLECTION = "data_dictionary"

# ============================================================================
# BGE Embedding (本地)
# ============================================================================
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
EMBEDDING_DEVICE = "cuda"  # GTX 1060 6GB

# ============================================================================
# 检索配置
# ============================================================================
RETRIEVAL_LAYERS = ["DM", "DWS", "ODS"]  # 检索优先级：从上到下
RETRIEVAL_TOP_K = 5                       # 每层返回 top-K 结果
RETRIEVAL_THRESHOLD = 0.5                 # 语义匹配相似度阈值
