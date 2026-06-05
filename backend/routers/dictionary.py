"""
数据字典管理路由 — 上传、索引、状态查询
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, File, UploadFile, Query

from backend.schemas import IndexStatusResponse, PreviewResponse, UploadResponse

router = APIRouter(prefix="/api/dictionary", tags=["数据字典"])

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _get_collection() -> tuple[Any | None, str]:
    """获取 ChromaDB collection，返回 (collection, error)"""
    try:
        from config import CHROMA_DIR, CHROMA_COLLECTION
        from chromadb import PersistentClient
        from chromadb.config import Settings as ChromaSettings

        client = PersistentClient(
            path=str(CHROMA_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = client.get_collection(CHROMA_COLLECTION)
        return collection, ""
    except Exception as e:
        return None, str(e)


@router.post("/upload", response_model=UploadResponse)
async def upload_dictionary(file: UploadFile = File(...)):
    """上传数据字典文件（CSV/XLSX），构建 ChromaDB 索引"""
    # Validate file type
    if not (file.filename.endswith(".csv") or file.filename.endswith(".xlsx")):
        return UploadResponse(success=False, error=f"不支持的文件类型: {file.filename}，仅支持 .csv / .xlsx")

    # Save uploaded file to data/
    suffix = ".xlsx" if file.filename.endswith(".xlsx") else ".csv"
    content = await file.read()

    # Preview parsing
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        if suffix == ".xlsx":
            df = pd.read_excel(tmp_path)
        else:
            df = pd.read_csv(tmp_path, encoding="utf-8-sig")

        # Validate required columns
        from dictionary.loader import _infer_column
        columns = list(df.columns)
        col_layer = _infer_column(columns, "layer")
        col_table = _infer_column(columns, "table_name")
        col_column = _infer_column(columns, "column_name")

        missing = []
        for label, col in [("layer/分层", col_layer), ("table_name/表名", col_table), ("column_name/字段名", col_column)]:
            if col is None:
                missing.append(label)

        if missing:
            os.unlink(tmp_path)
            return UploadResponse(success=False, error=f"缺少必要列: {', '.join(missing)}。实际列: {columns}")

        detected_layers = df[col_layer].dropna().unique().tolist()

        # Save to stable path
        stable_path = _DATA_DIR / f"uploaded_dict{suffix}"
        with open(stable_path, "wb") as f:
            f.write(content)

        # Build index
        from dictionary.loader import load_dictionary
        from dictionary.indexer import build_index

        data_dict = load_dictionary(str(stable_path))
        collection = build_index(data_dict, reset=True)

        os.unlink(tmp_path)

        return UploadResponse(
            success=True,
            layers=detected_layers,
            total_rows=len(df),
            collection_count=collection.count(),
            saved_path=str(stable_path),
        )

    except Exception as e:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return UploadResponse(success=False, error=str(e))


@router.get("/status", response_model=IndexStatusResponse)
async def index_status():
    """查询 ChromaDB 索引状态"""
    try:
        from config import CHROMA_COLLECTION
        collection, error = _get_collection()
        if error:
            return IndexStatusResponse(ready=False, error=error)
        return IndexStatusResponse(
            ready=True,
            count=collection.count(),
            collection=CHROMA_COLLECTION,
        )
    except Exception as e:
        return IndexStatusResponse(ready=False, error=str(e))


@router.get("/preview", response_model=PreviewResponse)
async def preview_file(path: str = Query(..., description="数据字典文件路径")):
    """预览数据字典文件（前 20 行）"""
    try:
        file_path = Path(path)
        if not file_path.exists():
            return PreviewResponse(columns=[], rows=[], error=f"文件不存在: {path}")

        if file_path.suffix.lower() == ".xlsx":
            df = pd.read_excel(file_path)
        else:
            df = pd.read_csv(file_path, encoding="utf-8-sig")

        preview = df.head(20)
        return PreviewResponse(
            columns=list(preview.columns),
            rows=preview.values.tolist(),
            total_rows=len(df),
        )
    except Exception as e:
        return PreviewResponse(columns=[], rows=[], error=str(e))
