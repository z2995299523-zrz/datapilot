"""
DataPilot UI 安全启动器

用法: python run_ui.py

相比直接 streamlit run ui/app.py:
  1. 设置 CUDA_VISIBLE_DEVICES="" — 彻底禁用 CUDA，避免 PyTorch + httpx 线程冲突 segfault
  2. BGE 走 CPU — 性能可接受（bge-small-zh-v1.5 仅 24MB）
  3. 限制 PyTorch 线程数为 1 — 减少线程池竞争
  4. 禁用 Streamlit 文件监控 — 避免重执行触发 segfault

工作原理:
  所有安全措施在 Streamlit 启动前完成。
  Streamlit 的 app.py 仍会执行 BGE 预加载（防御纵深），
  但此时 CUDA 已不可用，不会触发冲突。
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# ── 1. 环境变量（必须在 torch/huggingface 导入前设置） ──
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")   # 禁用 CUDA → 无 CUDA 上下文 → 无 segfault
os.environ.setdefault("EMBEDDING_DEVICE", "cpu")    # BGE 走 CPU

sys.path.insert(0, str(PROJECT_ROOT))

# ── 2. 预加载 BGE 模型（在 langchain_openai 之前） ──
print("[run_ui] Preloading BGE model...")
from embedding import get_embedding_model
_model = get_embedding_model()
print("[run_ui] BGE model loaded (CPU)")

# ── 3. 限制 PyTorch 线程数 ──
import torch
torch.set_num_threads(1)
print(f"[run_ui] PyTorch {torch.__version__} threads: 1")

# ── 4. 启动 Streamlit ──
print("[run_ui] Starting Streamlit -> http://localhost:8501")
from streamlit.web import cli as stcli
sys.argv = [
    "streamlit", "run", "ui/app.py",
    "--server.fileWatcherType", "none",   # 禁用文件监控，避免重载 crash
]
stcli.main()
