"""
需求分析路由 — 概念提取 → 检索 → 伪代码 → SQL 生成
"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends

from backend.auth import get_current_user

from backend.schemas import AnalysisRequest

router = APIRouter(prefix="/api/analysis", tags=["需求分析"])


def _get_collection():
    """获取 ChromaDB collection"""
    from config import CHROMA_DIR, CHROMA_COLLECTION
    from chromadb import PersistentClient
    from chromadb.config import Settings as ChromaSettings

    client = PersistentClient(
        path=str(CHROMA_DIR),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    return client.get_collection(CHROMA_COLLECTION)


def _resolve_dict_path(dict_path: str | None) -> str:
    """解析数据字典路径，fallback 到 demo"""
    if dict_path and Path(dict_path).exists():
        return dict_path
    demo_path = Path(__file__).parent.parent.parent / "demo" / "data_dict.csv"
    if demo_path.exists():
        return str(demo_path)
    return ""


@router.post("/full")
async def analyze_full(req: AnalysisRequest, user: dict = Depends(get_current_user)):
    """全链路分析：概念提取 → 分层检索 → 伪代码 → SQL

    返回所有中间结果供前端分步展示。
    """
    result = {
        "requirement_text": req.requirement_text,
        "extraction": None,
        "retrieval": None,
        "pseudocode": None,
        "sql": "",
        "error": "",
    }

    try:
        collection = _get_collection()

        # Step 1: Concept extraction
        from extractor.concept import extract_concepts
        extraction = extract_concepts(req.requirement_text)
        result["extraction"] = extraction.model_dump()

        if extraction.llm_error:
            result["error"] = f"概念提取 LLM 错误: {extraction.llm_error}"
            return result

        # Step 2: Retrieval
        from retrieval.engine import search
        retrieval = search(extraction.concepts, collection)
        result["retrieval"] = retrieval.model_dump()

        # Step 3: Pseudocode generation
        from generator.pseudocode import generate
        pseudocode = generate(
            req.requirement_text,
            retrieval,
            extraction.concepts,
        )
        result["pseudocode"] = pseudocode.model_dump()

        # Step 4: SQL generation (optional)
        if req.generate_sql and pseudocode.steps:
            dict_path = _resolve_dict_path(req.dict_path)
            if dict_path:
                from dictionary.loader import load_dictionary
                from generator.script import generate_sql_script

                data_dict = load_dictionary(dict_path)
                tables = {t.table_name: t for t in data_dict.tables}
                sql = generate_sql_script(
                    pseudocode=pseudocode,
                    tables=tables,
                    unmatched_concepts=retrieval.unmatched_concepts,
                    requirement_summary=req.requirement_text[:100],
                )
                result["sql"] = sql

    except Exception as e:
        result["error"] = str(e)

    return result


@router.post("/compare")
async def compare_expected(req: dict, user: dict = Depends(get_current_user)):
    """执行 SQL 并与预期 CSV 逐行逐列比对

    请求体:
        sql: str          — 要执行的 SQL
        db_conn_str: str  — 数据库连接字符串
        expected_csv: str — 预期 CSV 文件 base64 内容
    """
    import base64
    import io
    import tempfile

    sql = req.get("sql", "")
    db_conn_str = req.get("db_conn_str", "")
    expected_csv = req.get("expected_csv", "")

    if not sql or not db_conn_str or not expected_csv:
        return {"error": "缺少 sql / db_conn_str / expected_csv 参数"}

    try:
        from sqlalchemy import create_engine, text
        import pandas as pd

        # Execute SQL
        engine = create_engine(db_conn_str)
        with engine.connect() as conn:
            actual_df = pd.read_sql_query(text(sql), conn)

        # Decode expected CSV
        csv_bytes = base64.b64decode(expected_csv)
        expected_df = pd.read_csv(io.BytesIO(csv_bytes))

        # Save expected to temp file for compare_with_expected
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
            expected_df.to_csv(tmp.name, index=False)
            tmp_path = tmp.name

        from testing.expected_compare import compare_with_expected
        report = compare_with_expected(actual_df, tmp_path)

        try:
            import os
            os.unlink(tmp_path)
        except Exception:
            pass

        return {
            "overall_passed": report.overall_passed,
            "total_expected": report.total_expected,
            "total_actual": report.total_actual,
            "match_count": report.match_count,
            "mismatch_count": report.mismatch_count,
            "summary": report.summary,
            "missing_in_actual": report.missing_in_actual[:20] if report.missing_in_actual else [],
            "extra_in_actual": report.extra_in_actual[:20] if report.extra_in_actual else [],
            "value_diffs": [
                {
                    "key_values": d.key_values,
                    "column": d.column,
                    "expected_value": d.expected_value,
                    "actual_value": d.actual_value,
                    "diff_percent": d.diff_percent,
                }
                for d in (report.value_diffs or [])[:20]
            ],
            "actual_preview": json.loads(actual_df.head(10).to_json(orient="records", force_ascii=False)),
        }

    except Exception as e:
        return {"error": str(e)}
