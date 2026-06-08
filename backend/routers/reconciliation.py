"""
修复闭环路由 — L1 质量测试 + L2 逻辑比对 + L3 诊断 + 自动修复 + 重测
"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends

from backend.auth import get_current_user

from backend.schemas import ReconciliationRunRequest, ReconciliationTestsRequest

router = APIRouter(prefix="/api/reconciliation", tags=["修复闭环"])


def _resolve_dict_path(dict_path: str | None) -> str:
    """解析数据字典路径"""
    if dict_path and Path(dict_path).exists():
        return dict_path
    demo_path = Path(__file__).parent.parent.parent / "demo" / "data_dict.csv"
    if demo_path.exists():
        return str(demo_path)
    return ""


def _load_column_infos(dict_path: str) -> list:
    """加载 DM 层列信息用于测试"""
    from dictionary.loader import load_dictionary
    data_dict = load_dictionary(dict_path)
    dm_tables = [t for t in data_dict.tables if t.layer.value == "DM"]
    if dm_tables:
        return dm_tables[0].columns
    elif data_dict.tables:
        return data_dict.tables[0].columns
    return []


@router.post("/run")
async def run_reconciliation(req: ReconciliationRunRequest, user: dict = Depends(get_current_user)):
    """运行完整修复闭环：测试 → 诊断 → 修复 → 重测"""
    if not req.original_sql.strip():
        return {"status": "error", "error_message": "SQL 不能为空"}

    try:
        dict_path = _resolve_dict_path(req.dict_path)
        if not dict_path:
            return {"status": "error", "error_message": "未找到数据字典文件，请先上传"}

        column_infos = _load_column_infos(dict_path)
        pk_columns = [c.name for c in column_infos if c.is_primary_key]

        if not req.db_conn_str:
            # Dry-run: return preview
            return {
                "status": "dry_run",
                "message": "未提供数据库连接，仅展示流程预览",
                "loop_count": 0,
                "max_loops": req.max_loops,
                "column_count": len(column_infos),
                "pk_columns": pk_columns,
                "fix_history": [],
            }

        # Real execution
        from sqlalchemy import create_engine
        from reconciliation.graph import run_reconciliation as run_rec

        engine = create_engine(req.db_conn_str)
        with engine.connect() as conn:
            final_state = run_rec(
                conn=conn,
                original_sql=req.original_sql,
                column_infos=column_infos,
                requirement_text=req.requirement_text,
                pk_columns=pk_columns,
                expected_csv_path=req.expected_csv_path or "",
                max_loops=req.max_loops,
            )

        fix_history = json.loads(final_state.get("fix_history_json", "[]"))

        return {
            "status": final_state.get("status", "unknown"),
            "loop_count": len(fix_history),
            "max_loops": req.max_loops,
            "error_message": final_state.get("error_message", ""),
            "fix_history": fix_history,
            "quality_report": _safe_json_load(final_state.get("quality_report_json")),
            "comparison_report": _safe_json_load(final_state.get("comparison_report_json")),
            "diagnosis_report": _safe_json_load(final_state.get("diagnosis_report_json")),
        }

    except Exception as e:
        return {"status": "error", "error_message": str(e), "fix_history": []}


@router.post("/tests")
async def run_tests_only(req: ReconciliationTestsRequest, user: dict = Depends(get_current_user)):
    """仅运行 L1 质量测试（不进入修复闭环）"""
    if not req.original_sql.strip():
        return {"error": "SQL 不能为空"}

    if not req.db_conn_str:
        return {"error": "需要数据库连接字符串"}

    try:
        dict_path = _resolve_dict_path(req.dict_path)
        if not dict_path:
            return {"error": "未找到数据字典文件"}

        column_infos = _load_column_infos(dict_path)
        pk_columns = [c.name for c in column_infos if c.is_primary_key]

        from sqlalchemy import create_engine
        from testing.quality import run_quality_tests

        engine = create_engine(req.db_conn_str)
        with engine.connect() as conn:
            quality_report = run_quality_tests(
                conn=conn,
                original_sql=req.original_sql,
                column_infos=column_infos,
                pk_columns=pk_columns,
            )

        return quality_report.model_dump()

    except Exception as e:
        return {"error": str(e)}


def _safe_json_load(json_str: str | None):
    """安全解析 JSON，失败返回 None"""
    if not json_str:
        return None
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return None
