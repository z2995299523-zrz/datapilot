"""
AppConfig — 应用配置（不可变，可注入，无副作用）

使用方式:
    # 生产环境：从环境变量加载（含副作用：HF_ENDPOINT / .env / mkdir）
    config = AppConfig.from_env()

    # 测试环境：直接构造（无副作用）
    config = AppConfig(
        llm_api_key="test-key",
        ...
    )

    # 新代码：构造器注入
    class MyService:
        def __init__(self, config: AppConfig):
            self.config = config

    # 旧代码：仍可用 config.py 兼容层
    from config import LLM_API_KEY  # 仍然有效
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True)
class AppConfig:
    """DataPilot 应用配置 — frozen, 无副作用, 可注入

    Attributes:
        project_root: 项目根目录
        data_dir: 数据目录（ChromaDB 等）
        chroma_dir: ChromaDB 持久化目录
        demo_dir: 演示数据目录
        llm_api_key: DeepSeek API Key
        llm_base_url: DeepSeek API 地址
        llm_model: DeepSeek 模型名
        llm_temperature: LLM 温度参数
        llm_max_retry: LLM 调用最大重试次数
        chroma_collection: ChromaDB 集合名
        embedding_model: BGE 模型名
        embedding_device: BGE 推理设备
        retrieval_layers: 检索层优先级
        retrieval_top_k: 每层返回 top-K
        retrieval_threshold: 语义相似度阈值
    """

    # ── 项目路径 ──
    project_root: Path
    data_dir: Path
    chroma_dir: Path
    demo_dir: Path

    # ── DeepSeek ──
    llm_api_key: str
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.1
    llm_max_retry: int = 3

    # ── ChromaDB ──
    chroma_collection: str = "data_dictionary"

    # ── BGE Embedding ──
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_device: str = "cuda"

    # ── 检索 ──
    retrieval_layers: tuple[str, ...] = ("DM", "DWS", "ODS")
    retrieval_top_k: int = 5
    retrieval_threshold: float = 0.5

    # ── 默认实例（惰性，由 config.py 兼容层触发） ──
    _default: ClassVar["AppConfig | None"] = None

    @classmethod
    def from_env(cls, *, project_root: Path | None = None) -> "AppConfig":
        """从环境变量创建 AppConfig。

        副作用（仅此方法）:
            1. 设置 HF_ENDPOINT 镜像（必须在 huggingface 加载前）
            2. 加载 .env 文件
            3. 创建 data/ 和 chroma_db/ 目录

        Args:
            project_root: 项目根目录，None 时自动推断（取本文件向上两级）
        """
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent

        # 副作用 1: HF 镜像 — 必须在任何 huggingface 导入之前
        if "HF_ENDPOINT" not in os.environ:
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

        # 副作用 2: 加载 .env
        from dotenv import load_dotenv
        load_dotenv(project_root / ".env")

        # 副作用 3: 确保数据目录存在
        data_dir = project_root / "data"
        chroma_dir = data_dir / "chroma_db"
        demo_dir = project_root / "demo"
        data_dir.mkdir(parents=True, exist_ok=True)
        chroma_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            project_root=project_root,
            data_dir=data_dir,
            chroma_dir=chroma_dir,
            demo_dir=demo_dir,
            llm_api_key=os.getenv("DEEPSEEK_API_KEY", "your-deepseek-api-key"),
            llm_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            llm_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            llm_temperature=0.1,
            llm_max_retry=3,
            chroma_collection="data_dictionary",
            embedding_model="BAAI/bge-small-zh-v1.5",
            embedding_device=os.getenv("EMBEDDING_DEVICE", "cuda"),
            retrieval_layers=("DM", "DWS", "ODS"),
            retrieval_top_k=5,
            retrieval_threshold=0.5,
        )

    @classmethod
    def get_default(cls) -> "AppConfig":
        """获取默认配置实例（惰性创建，供兼容层使用）"""
        if cls._default is None:
            # 绕过 frozen dataclass 的 ClassVar 限制
            object.__setattr__(cls, "_default", cls.from_env())
        return cls._default
