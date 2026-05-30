"""
统一 LLM 测试代码生成器

核心理念：表结构 + 业务逻辑 + 原始SQL + 数据字典 → LLM → 完整测试SQL套件

不再用规则模板逐个拼 SQL（_pk_sql, _null_sql, _length_sql...），
而是把全部上下文发给 LLM，让 LLM 一次性生成覆盖所有维度的测试代码。

LLM 主路径 + 规则模板 fallback（LLM 不可用时回退到传统方法）。

用法：
    from testing.llm_tester import generate_test_suite, execute_test_suite
    suite = generate_test_suite(original_sql, column_infos, requirement=...)
    results = execute_test_suite(conn, suite)
    report = parse_suite_results(results, suite)
"""
import json
import re
from typing import Any, Optional

from models import (
    ColumnInfo, LLMTestCase, LLMTestSuiteResponse,
)
from callbacks.token_tracker import TokenTracker
from callbacks.audit_logger import AuditLogger


# ============================================================================
# 生成
# ============================================================================

def generate_test_suite(
    original_sql: str,
    column_infos: list[ColumnInfo],
    requirement_text: str = "",
    pseudocode_text: str = "",
    source_table_counts: dict[str, int] | None = None,
) -> LLMTestSuiteResponse:
    """LLM 生成完整测试 SQL 套件

    把表结构、业务逻辑、原始 SQL 全部发给 LLM，一次生成完整测试代码。

    Args:
        original_sql: 需要测试的原始 SQL
        column_infos: 数据字典列信息
        requirement_text: 业务需求文档
        pseudocode_text: 分析伪代码
        source_table_counts: 源表行数（{表名: 行数}）

    Returns:
        LLMTestSuiteResponse 含 test_cases 列表，每项包含可直接执行的 test_sql
    """
    # ── 路径 1: LLM 生成 ──
    try:
        suite = _llm_generate_tests(
            original_sql, column_infos,
            requirement_text, pseudocode_text, source_table_counts,
        )
        if suite and suite.test_cases:
            return suite
    except Exception:
        pass

    # ── 路径 2: 规则模板 fallback ──
    return _template_generate_tests(original_sql, column_infos)


def _llm_generate_tests(
    original_sql: str,
    column_infos: list[ColumnInfo],
    requirement_text: str,
    pseudocode_text: str,
    source_table_counts: dict[str, int] | None,
) -> Optional[LLMTestSuiteResponse]:
    """LLM 生成测试套件"""
    from llm_client import chat_json
    from extractor.prompts import build_test_generation_prompt

    col_info_text = _format_column_info(column_infos)

    source_text = ""
    if source_table_counts:
        source_text = "\n".join(f"- {name}: ~{count:,} 行" for name, count in source_table_counts.items())

    prompt = build_test_generation_prompt()
    messages = prompt.format_messages(
        original_sql=original_sql,
        column_info=col_info_text,
        requirement=requirement_text or "（未提供需求文档）",
        pseudocode=pseudocode_text or "（未提供伪代码）",
        source_tables=source_text or "（未提供源表规模）",
    )

    system = str(messages[0].content)
    user = str(messages[1].content)

    tracker = TokenTracker()
    audit = AuditLogger()

    raw = chat_json(
        system_prompt=system,
        user_message=user,
        callbacks=[tracker, audit],
    )

    # Pydantic 校验
    suite = LLMTestSuiteResponse(**raw)
    return suite


def _template_generate_tests(
    original_sql: str,
    column_infos: list[ColumnInfo],
) -> LLMTestSuiteResponse:
    """规则模板生成测试套件（LLM 不可用时的 fallback）

    使用现有的 generate_all_checks_sql 作为降级方案。
    """
    from testing.quality import generate_all_checks_sql

    try:
        sql = generate_all_checks_sql(original_sql, column_infos)
    except Exception:
        sql = "-- 测试生成失败"

    # 将一条 UNION ALL SQL 包装为单个 test_case
    tc = LLMTestCase(
        check_type="full_suite",
        column_name="",
        description="规则引擎生成的完整测试套件（LLM 不可用时的降级方案）",
        test_sql=sql,
        expected_behavior="所有检查项返回空结果集 = 通过",
    )

    return LLMTestSuiteResponse(
        suite_description="规则引擎降级测试套件",
        test_cases=[tc],
        notes=["LLM 不可用，使用规则模板生成。建议检查 API Key 配置后重新生成。"],
    )


# ============================================================================
# 执行
# ============================================================================

def execute_test_suite(
    conn,
    suite: LLMTestSuiteResponse,
) -> list[dict[str, Any]]:
    """执行 LLM 生成的测试套件

    逐条执行 test_sql，收集违规结果。

    Args:
        conn: 数据库连接
        suite: LLM 生成的测试套件

    Returns:
        每条测试的执行结果列表: [{test_case, passed, rows, error}]
    """
    results = []
    for tc in suite.test_cases:
        try:
            cursor = conn.execute(tc.test_sql)
            rows = cursor.fetchall()
            results.append({
                "check_type": tc.check_type,
                "description": tc.description,
                "column_name": tc.column_name,
                "passed": len(rows) == 0,
                "violation_count": len(rows),
                "violations": rows[:20],  # 最多返回 20 条违规
                "error": None,
            })
        except Exception as e:
            results.append({
                "check_type": tc.check_type,
                "description": tc.description,
                "column_name": tc.column_name,
                "passed": False,
                "violation_count": 0,
                "violations": [],
                "error": str(e),
            })

    return results


# ============================================================================
# 解析 → QualityReport
# ============================================================================

def parse_suite_results(
    results: list[dict[str, Any]],
    total_rows: int = 0,
) -> "QualityReport":
    """将测试套件执行结果解析为 QualityReport

    Args:
        results: execute_test_suite 的返回值
        total_rows: 原始查询的行数

    Returns:
        QualityReport
    """
    from testing.quality import QualityReport, QualityCheckResult

    checks = []
    for r in results:
        passed = r["passed"]
        violation_count = r["violation_count"]
        detail = r["description"]
        actual = f"通过" if passed else f"{violation_count} 条违规"
        expected = "0 条违规"

        if r["error"]:
            actual = f"执行错误: {r['error']}"
            passed = False

        checks.append(QualityCheckResult(
            check_type=r["check_type"],
            column=r["column_name"],
            passed=passed,
            detail=detail,
            actual_value=actual,
            expected_value=expected,
        ))

    return QualityReport(
        total_rows=total_rows,
        total_columns=0,
        checks=checks,
    )


# ============================================================================
# 一键：生成 + 执行 + 报告
# ============================================================================

def run_llm_test_suite(
    conn,
    original_sql: str,
    column_infos: list[ColumnInfo],
    requirement_text: str = "",
    pseudocode_text: str = "",
    source_table_counts: dict[str, int] | None = None,
) -> "QualityReport":
    """一键运行 LLM 测试套件：生成 → 执行 → 解析

    Args:
        conn: 数据库连接
        original_sql: 原始 SQL
        column_infos: 列信息
        requirement_text: 业务需求
        pseudocode_text: 伪代码
        source_table_counts: 源表行数

    Returns:
        QualityReport
    """
    # 1. LLM 生成测试套件
    suite = generate_test_suite(
        original_sql, column_infos,
        requirement_text, pseudocode_text, source_table_counts,
    )

    # 2. 获取总行数
    try:
        from testing.quality import generate_row_count_sql
        cur = conn.execute(generate_row_count_sql(original_sql))
        total = cur.fetchone()[0]
    except Exception:
        total = 0

    # 3. 执行
    results = execute_test_suite(conn, suite)

    # 4. 解析
    return parse_suite_results(results, total)


# ============================================================================
# 辅助
# ============================================================================

def _format_column_info(column_infos: list[ColumnInfo]) -> str:
    """格式化列信息为 LLM 可读的 Markdown"""
    lines = ["| 列名 | 类型 | 主键 | 外键 | 注释 | 码值 |",
             "|------|------|------|------|------|------|"]
    for ci in column_infos:
        pk = "PK" if ci.is_primary_key else ""
        fk = f"→ {ci.referenced_table}" if ci.is_foreign_key and ci.referenced_table else ""
        codes = ", ".join(f"{cv.value}={cv.meaning}" for cv in ci.code_values) if ci.code_values else ""
        lines.append(f"| {ci.name} | {ci.data_type} | {pk} | {fk} | {ci.comment} | {codes} |")
    return "\n".join(lines)
