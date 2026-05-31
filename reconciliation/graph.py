"""
LangGraph 修复闭环 — StateGraph 组装

流程图:
    START → run_tests → passed? END : diagnose
                           diagnose → auto_fixable? auto_fix : manual_report
                           auto_fix → retest → (loop) run_tests
                           manual_report → END

数据库连接通过闭包传给 run_tests 节点，避免 LangGraph config 序列化问题。
"""
import json
from typing import Any

from langgraph.graph import StateGraph, END

from reconciliation.state import ReconciliationState
from reconciliation.nodes import (
    run_tests_node,
    diagnose_node,
    auto_fix_node,
    manual_report_node,
    retest_node,
    reanalyze_node,
)
from reconciliation.router import after_run_tests, after_diagnose, after_retest


def build_graph(conn=None) -> StateGraph:
    """构建修复闭环的 StateGraph

    Args:
        conn: 数据库连接，通过闭包传给 run_tests 节点
    """
    workflow = StateGraph(ReconciliationState)

    # 闭包捕获 conn
    def _run_tests(state: ReconciliationState) -> dict:
        return run_tests_node(state, conn=conn)

    workflow.add_node("run_tests", _run_tests)
    workflow.add_node("diagnose", diagnose_node)
    workflow.add_node("auto_fix", auto_fix_node)
    workflow.add_node("manual_report", manual_report_node)
    workflow.add_node("retest", retest_node)
    workflow.add_node("reanalyze", reanalyze_node)

    workflow.set_entry_point("run_tests")

    workflow.add_conditional_edges(
        "run_tests", after_run_tests,
        {"diagnose": "diagnose", "__end__": END},
    )
    workflow.add_conditional_edges(
        "diagnose", after_diagnose,
        {"auto_fix": "auto_fix", "manual_report": "manual_report", "reanalyze": "reanalyze"},
    )
    workflow.add_edge("auto_fix", "retest")
    workflow.add_edge("reanalyze", "retest")
    workflow.add_edge("manual_report", END)
    workflow.add_conditional_edges(
        "retest", after_retest,
        {"run_tests": "run_tests", "__end__": END},
    )

    return workflow.compile()


def run_reconciliation(
    conn,
    original_sql: str,
    column_infos: list,
    requirement_text: str = "",
    pk_columns: list[str] | None = None,
    expected_sql: str = "",
    source_table_counts: dict[str, int] | None = None,
    join_pairs: list[tuple[str, str]] | None = None,
    max_loops: int = 3,
) -> dict:
    """一键启动修复闭环

    Args:
        conn: 数据库连接
        original_sql: 要测试的原始 SQL
        column_infos: 列信息列表
        requirement_text: 需求文档
        pk_columns: 主键列
        expected_sql: 预期结果 SQL
        source_table_counts: 源表行数（用于笛卡尔积检测）
        join_pairs: JOIN 表对（用于笛卡尔积检测）
        max_loops: 最大重试次数

    Returns:
        最终的 state dict
    """
    col_data = []
    for ci in column_infos:
        item = {
            "name": ci.name, "data_type": ci.data_type, "comment": ci.comment,
            "is_primary_key": ci.is_primary_key, "is_foreign_key": ci.is_foreign_key,
            "referenced_table": ci.referenced_table,
            "code_values": [{"value": cv.value, "meaning": cv.meaning} for cv in ci.code_values],
        }
        col_data.append(item)

    if pk_columns is None:
        pk_columns = [ci.name for ci in column_infos if ci.is_primary_key]

    initial_state: ReconciliationState = {
        "requirement_text": requirement_text,
        "original_sql": original_sql,
        "column_infos_json": json.dumps(col_data, ensure_ascii=False),
        "pk_columns_json": json.dumps(pk_columns, ensure_ascii=False),
        "expected_sql": expected_sql,
        "loop_count": 0,
        "max_loops": max_loops,
        "status": "running",
        "error_message": "",
        "fix_history_json": "[]",
        "quality_report_json": "",
        "comparison_report_json": "",
        "diagnosis_report_json": "",
    }

    graph = build_graph(conn=conn)
    return graph.invoke(initial_state)
