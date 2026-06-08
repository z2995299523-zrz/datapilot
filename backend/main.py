"""
DataPilot FastAPI 后端 — 前后端分离架构

启动: uvicorn backend.main:app --reload --port 8000
文档: http://localhost:8000/docs
"""

import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path，以便导入 extractor/retrieval 等模块
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# 🔧 预加载 BGE embedding 模型（必须在 langchain_openai 之前）
#   langchain_openai 的 httpx 线程初始化会与 PyTorch CUDA 冲突，
#   导致 SentenceTransformer 在 CUDA 设备上加载时 segfault (exit 139)
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("EMBEDDING_DEVICE", "cpu")

from embedding import get_embedding_model
get_embedding_model()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import dictionary, analysis, reconciliation, modeling, auth, admin
from backend.schemas import HealthResponse

app = FastAPI(
    title="DataPilot API",
    description="需求文档 → SQL 脚本 全链路引擎。概念提取 → 分层检索 → 伪代码 → SQL → 测试 → 修复。",
    version="5.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — 允许前端开发服务器
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(dictionary.router)
app.include_router(analysis.router)
app.include_router(reconciliation.router)
app.include_router(modeling.router)
app.include_router(auth.router)
app.include_router(admin.router)


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """健康检查 + 索引状态"""
    import os
    try:
        from config import CHROMA_DIR, CHROMA_COLLECTION
        from chromadb import PersistentClient
        from chromadb.config import Settings as ChromaSettings

        client = PersistentClient(
            path=str(CHROMA_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collections = client.list_collections()
        existing = [c for c in collections if c.name == CHROMA_COLLECTION]
        index_ready = len(existing) > 0
        index_count = client.get_collection(CHROMA_COLLECTION).count() if index_ready else 0
    except Exception:
        index_ready = False
        index_count = 0

    langsmith_configured = bool(
        os.getenv("LANGCHAIN_API_KEY")
        and os.getenv("LANGCHAIN_API_KEY") != "your-langsmith-api-key"
    )

    return HealthResponse(
        status="ok",
        index_ready=index_ready,
        index_count=index_count,
        langsmith_configured=langsmith_configured,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
