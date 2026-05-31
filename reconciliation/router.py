"""
LangGraph 条件路由 — 决定修复闭环的下一步走向

路由规则:
  1. after_run_tests: passed → END, 否则 → diagnose
  2. after_diagnose: 有可自动修复项 → auto_fix, 否则 → manual_report
  3. after_retest:   status==running → run_tests, 否则 → END
"""
import json

from reconciliation.state import ReconciliationState
from testing.diagnosis import DiagnosisReport


def after_run_tests(state: ReconciliationState) -> str:
    """测试完成后的路由

    Returns:
        "__end__" 或 "diagnose"
    """
    status = state.get("status", "")
    if status == "passed":
        return "__end__"

    # 检查是否因 max_loops 或 error 直接结束
    if status in ("failed",):
        return "__end__"

    return "diagnose"


def after_diagnose(state: ReconciliationState) -> str:
    """诊断完成后的路由 — 区分语法错误和语义错误

    路由规则:
      - 全是语法错误且 is_auto_fixable → "auto_fix"
      - 包含语义错误 → "reanalyze"
      - 无自动修复项 → "manual_report"

    Returns:
        "auto_fix" / "reanalyze" / "manual_report"
    """
    diag_json = state.get("diagnosis_report_json", "")
    if not diag_json:
        return "manual_report"

    try:
        data = json.loads(diag_json)
        items = data.get("items", [])
    except Exception:
        return "manual_report"

    if not items:
        return "manual_report"

    # 检查是否有可自动修复的项
    auto_fixable = [it for it in items if it.get("is_auto_fixable")]
    if not auto_fixable:
        # 无可自动修复项 → 检查是否有语义错误（需要重新分析）
        has_semantic = any(
            it.get("fix_level") == "semantic"
            for it in items
        )
        if has_semantic:
            return "reanalyze"
        return "manual_report"

    # 有可自动修复项 → 语法错误走 auto_fix
    return "auto_fix"


def after_retest(state: ReconciliationState) -> str:
    """重测节点后的路由

    Returns:
        "run_tests" 或 "__end__"
    """
    status = state.get("status", "")
    if status == "running":
        return "run_tests"
    # failed (max_loops exceeded), manual_fix_needed, passed
    return "__end__"
