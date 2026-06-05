"""
数仓建模路由 — 从业务数据库 schema 自动搭建分层数仓模型
"""

import json
import tempfile
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, UploadFile

from models import (ModelingRequest, ModelingResult, EvolveRequest,
                    TableInfo, DataLayer)
from backend.schemas import SchemaUploadResponse

router = APIRouter(prefix="/api/modeling", tags=["数仓建模"])

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# In-memory cache for the latest modeling result
_latest_result: ModelingResult | None = None


@router.post("/upload", response_model=SchemaUploadResponse)
async def upload_schema(file: UploadFile = File(...)):
    """上传业务数据库 schema 文件（CSV/XLSX），返回解析后的表结构预览"""
    if not (file.filename.endswith(".csv") or file.filename.endswith(".xlsx")):
        return SchemaUploadResponse(success=False, error=f"不支持的文件类型: {file.filename}")

    content = await file.read()
    suffix = ".xlsx" if file.filename.endswith(".xlsx") else ".csv"

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        from dictionary.loader import load_dictionary
        from dictionary.loader import _infer_column

        if suffix == ".xlsx":
            df = pd.read_excel(tmp_path)
        else:
            df = pd.read_csv(tmp_path, encoding="utf-8-sig")

        columns = list(df.columns)
        col_layer = _infer_column(columns, "layer")
        col_table = _infer_column(columns, "table_name")

        # Basic validation
        if col_table is None:
            return SchemaUploadResponse(success=False, error=f"缺少 table_name/表名 列。实际列: {columns}")

        data_dict = load_dictionary(tmp_path)
        tables = data_dict.tables

        # Save to stable path
        stable_path = _DATA_DIR / f"uploaded_schema{suffix}"
        with open(stable_path, "wb") as f:
            f.write(content)

        import os
        os.unlink(tmp_path)

        return SchemaUploadResponse(
            success=True,
            source_name=file.filename,
            tables_detected=len(tables),
            columns_detected=sum(len(t.columns) for t in tables),
            saved_path=str(stable_path),
        )
    except Exception as e:
        return SchemaUploadResponse(success=False, error=str(e))


@router.post("/analyze", response_model=ModelingResult)
async def analyze(req: ModelingRequest):
    """全链路一键数仓建模"""
    from modeling.engine import run_modeling
    global _latest_result
    result = run_modeling(req)
    _latest_result = result
    return result


@router.post("/classify")
async def classify(req: ModelingRequest):
    """仅表角色分类"""
    from modeling.classifier import classify_all
    result = classify_all(req.tables, llm_enabled=req.enable_llm)
    return {k: v.model_dump() for k, v in result.items()}


@router.post("/detect-relations")
async def detect_relations(req: ModelingRequest):
    """仅 FK-PK 关系检测"""
    from modeling.relation_detector import detect_relationships
    result = detect_relationships(req.tables, llm_enabled=req.enable_llm)
    return [r.model_dump() for r in result]


@router.post("/detect-codes")
async def detect_codes(req: ModelingRequest):
    """仅码值列检测"""
    from modeling.code_detector import detect_code_columns
    result = detect_code_columns(req.tables)
    return [c.model_dump() for c in result]


@router.post("/validate")
async def validate(req: ModelingRequest):
    """仅质量校验（需要先运行 analyze）"""
    from modeling.quality_validator import validate_quality
    result = validate_quality(
        layers={}, tables=req.tables,
        classifications={}, relationships=[], schemas=[],
    )
    return [q.model_dump() for q in result]


@router.post("/schema")
async def detect_schema(req: ModelingRequest):
    """仅模式分类（需要先运行 classify）"""
    from modeling.classifier import classify_all
    from modeling.relation_detector import detect_relationships
    from modeling.schema_classifier import classify_schema

    classifications = classify_all(req.tables, llm_enabled=req.enable_llm)
    relationships = detect_relationships(req.tables, llm_enabled=req.enable_llm)
    schema_def = classify_schema(req.tables, relationships, classifications,
                                 name=req.source_name or "main")
    return schema_def.model_dump()


@router.post("/evolve", response_model=ModelingResult)
async def evolve(req: EvolveRequest):
    """模型演进：在已有模型基础上新增/合并表"""
    from modeling.evolve import evolve_model
    global _latest_result
    result = evolve_model(req)
    _latest_result = result
    return result


@router.get("/result")
async def get_result():
    """获取最近一次建模结果"""
    global _latest_result
    if _latest_result is None:
        return {"error": "尚未执行建模，请先 POST /api/modeling/analyze"}
    return _latest_result.model_dump()
