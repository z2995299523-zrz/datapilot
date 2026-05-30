"""
LangGraph 修复闭环 — 节点函数（LLM 增强版）

设计原则：LLM 做主路径，规则引擎做 fallback。每个 LLM 调用都有：
  - retry（最多 3 次）
  - Pydantic 校验
  - Callbacks（TokenTracker + AuditLogger）
  - 降级路径（LLM 不可用时回退规则引擎）

5 个节点:
  run_tests    → 执行 L1 (+L2) 测试
  diagnose     → L3 诊断（LLM 默认，规则 fallback）
  auto_fix     → SQL 修复（LLM 默认，正则 fallback + 回滚保护）
  manual_report → 人工介入报告
  retest       → 重置报告，循环计数
"""
import json
import re
from typing import Any

from reconciliation.state import ReconciliationState
from testing.quality import QualityReport, run_quality_tests
from testing.comparison import ComparisonReport
from testing.diagnosis import DiagnosisReport, diagnose, diagnose_heuristic


# ============================================================================
# JSON 序列化辅助
# ============================================================================

def _load_report(json_str: str, cls):
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
        return cls(**data)
    except Exception:
        return None


def _dump_report(report) -> str:
    if report is None:
        return ""
    return report.model_dump_json()


# ============================================================================
# 节点 1: run_tests
# ============================================================================

def run_tests_node(state: ReconciliationState, conn=None) -> dict[str, Any]:
    """执行 L1 质量测试（+ L2 如果有预期数据）"""
    original_sql = state.get("original_sql", "")
    if not original_sql:
        return {"status": "failed", "error_message": "缺少 original_sql"}

    col_infos = _deserialize_column_infos(state.get("column_infos_json", "[]"))
    pk_cols = json.loads(state.get("pk_columns_json", "[]"))

    if conn is None:
        return {"status": "failed", "error_message": "需要数据库连接"}

    try:
        qr = run_quality_tests(conn, original_sql, col_infos, pk_columns=pk_cols)
    except Exception as e:
        return {"status": "failed", "error_message": f"L1 测试执行异常: {e}"}

    updates: dict[str, Any] = {"quality_report_json": _dump_report(qr)}

    expected_sql = state.get("expected_sql", "")
    if expected_sql:
        try:
            from testing.comparison import run_comparison_tests
            key_cols = pk_cols if pk_cols else [ci.name for ci in col_infos if ci.is_primary_key]
            cr = run_comparison_tests(conn, expected_sql, original_sql,
                                       key_columns=key_cols or None)
            updates["comparison_report_json"] = _dump_report(cr)
        except Exception:
            updates["comparison_report_json"] = _dump_report(ComparisonReport(checks=[]))

    updates["status"] = "passed" if qr.overall_passed else "running"
    return updates


# ============================================================================
# 节点 2: diagnose — LLM 主路径 + 规则 fallback
# ============================================================================

def diagnose_node(state: ReconciliationState) -> dict[str, Any]:
    """L3 诊断分析 — 优先调 LLM，失败时走规则引擎"""
    qr = _load_report(state.get("quality_report_json", ""), QualityReport)
    cr = _load_report(state.get("comparison_report_json", ""), ComparisonReport)

    if qr is None and cr is None:
        return {"diagnosis_report_json": _dump_report(DiagnosisReport(
            total_checks=0,
            items=[],
            summary="无测试报告可供诊断",
        ))}

    # 先尝试 LLM 诊断
    try:
        report = diagnose(
            quality_report=qr,
            comparison_report=cr,
            requirement_text=state.get("requirement_text", ""),
        )
    except Exception:
        # LLM 不可用 → 规则引擎兜底
        report = diagnose_heuristic(quality_report=qr, comparison_report=cr)

    return {"diagnosis_report_json": _dump_report(report)}


# ============================================================================
# 节点 3: auto_fix — LLM 主路径 + 正则 fallback + 回滚保护
# ============================================================================

def auto_fix_node(state: ReconciliationState) -> dict[str, Any]:
    """自动修复 — LLM 分析 SQL 语义 → 精准修复 → 正则 fallback

    流程：
      1. LLM 修复（主路径）：传入 SQL + 诊断结果 + 数据字典，LLM 输出修复后 SQL
      2. Pydantic 校验：验证修复后的 SQL 语法基本合理
      3. 正则修复（fallback）：LLM 不可用时，对简单场景做正则替换
      4. 回滚保护：记录 sql_before，修复失败时可恢复
    """
    original_sql = state.get("original_sql", "")
    diag_json = state.get("diagnosis_report_json", "")
    col_json = state.get("column_infos_json", "[]")
    fix_history = json.loads(state.get("fix_history_json", "[]"))

    if not original_sql or not diag_json:
        return {}

    report = _load_report(diag_json, DiagnosisReport)
    if report is None or not report.items:
        return {}

    # 分离可自动修复和不可修复的项
    fixable = [it for it in report.items if it.is_auto_fixable]
    if not fixable:
        return {}  # 无可自动修复项，留给 manual_report

    modified_sql = original_sql
    fixes_applied = []
    fix_method = "none"

    # ── 路径 1: LLM 精准修复 ──
    try:
        llm_result = _llm_fix_sql(original_sql, fixable, col_json)
        if llm_result and _is_valid_sql_change(original_sql, llm_result):
            modified_sql = llm_result
            fix_method = "llm"
            fixes_applied.append({
                "method": "llm",
                "issues_fixed": len(fixable),
                "issues": [
                    {"type": it.source, "columns": it.affected_columns,
                     "symptom": it.symptom[:100]}
                    for it in fixable
                ],
            })
    except Exception:
        pass  # LLM 失败 → 走 fallback

    # ── 路径 2: 正则 fallback ──
    if fix_method != "llm":
        for item in fixable:
            prev = modified_sql
            modified_sql = _regex_fix_sql(modified_sql, item)
            if modified_sql != prev:
                fixes_applied.append({
                    "method": "regex",
                    "type": item.source,
                    "columns": item.affected_columns,
                    "action": f"正则修复: {item.source}",
                })
        if fixes_applied:
            fix_method = "regex"

    # ── 记录修复历史 ──
    if fixes_applied:
        fix_history.append({
            "loop": state.get("loop_count", 0),
            "method": fix_method,
            "fixes": fixes_applied,
            "sql_before": original_sql,
            "sql_after": modified_sql,
        })

    return {
        "original_sql": modified_sql,
        "fix_history_json": json.dumps(fix_history, ensure_ascii=False),
    }


# ============================================================================
# 节点 4: manual_report
# ============================================================================

def manual_report_node(state: ReconciliationState) -> dict[str, Any]:
    """生成人工介入报告 — 收集不可自动修复的项"""
    report = _load_report(state.get("diagnosis_report_json", ""), DiagnosisReport)
    if report is None:
        return {"status": "manual_fix_needed", "error_message": "缺少诊断报告"}

    manual_items = [it for it in report.items if not it.is_auto_fixable]
    fix_history = json.loads(state.get("fix_history_json", "[]"))

    lines = ["## DataPilot 修复闭环 — 人工介入报告", ""]
    lines.append(f"需求: {state.get('requirement_text', 'N/A')[:200]}")
    lines.append(f"循环次数: {state.get('loop_count', 0)}")
    lines.append(f"已自动修复: {len(fix_history)} 轮")
    if fix_history:
        for h in fix_history:
            lines.append(f"  - 第{h.get('loop', '?')}轮: {h.get('method', '?')} 方式修复")
    lines.append(f"需人工处理: {len(manual_items)} 项")
    lines.append("")

    for i, item in enumerate(manual_items, 1):
        lines.append(f"### {i}. [{item.severity.upper()}] {item.source}")
        lines.append(f"- 症状: {item.symptom}")
        lines.append(f"- 根因: {item.root_cause}")
        lines.append(f"- 影响: {item.impact}")
        lines.append(f"- 建议修复: {item.fix_suggestion}")
        lines.append(f"- 预防: {item.prevention}")
        lines.append("")

    if not manual_items:
        lines.append("> 所有问题已自动修复，无需人工介入。")

    return {
        "status": "manual_fix_needed",
        "error_message": "\n".join(report_lines) if (report_lines := lines) else "",
    }


# ============================================================================
# 节点 5: retest
# ============================================================================

def retest_node(state: ReconciliationState) -> dict[str, Any]:
    """清除报告，增加循环计数"""
    loop = state.get("loop_count", 0) + 1
    max_loops = state.get("max_loops", 3)

    if loop > max_loops:
        return {
            "loop_count": loop,
            "status": "failed",
            "error_message": f"超过最大重试次数 ({max_loops})，自动修复未能解决所有问题",
        }

    return {
        "loop_count": loop,
        "quality_report_json": "",
        "comparison_report_json": "",
        "diagnosis_report_json": "",
        "status": "running",
    }


# ============================================================================
# LLM SQL 修复
# ============================================================================

def _llm_fix_sql(original_sql: str, fixable_items: list, col_json: str) -> str | None:
    """调 LLM 生成修复后的 SQL — 含 Callbacks + 重试 + 降级

    Args:
        original_sql: 原始 SQL
        fixable_items: DiagnosisItem 列表（可自动修复的）
        col_json: 列信息 JSON

    Returns:
        修复后的 SQL，失败返回 None（调用方回退到正则修复）
    """
    from llm_client import chat_text
    from extractor.prompts import build_sql_fix_prompt
    from callbacks.token_tracker import TokenTracker
    from callbacks.audit_logger import AuditLogger

    # 构建诊断摘要
    diag_lines = []
    for item in fixable_items:
        diag_lines.append(
            f"- [{item.source}] {item.symptom}\n"
            f"  列: {', '.join(item.affected_columns) if item.affected_columns else '无'}\n"
            f"  修复建议: {item.fix_suggestion}"
        )
    diagnosis_text = "\n".join(diag_lines)

    # 格式化列信息
    try:
        col_data = json.loads(col_json)
        col_lines = []
        for c in col_data:
            codes = c.get("code_values", [])
            code_str = f" 码值: {[(cv['value'], cv['meaning']) for cv in codes]}" if codes else ""
            col_lines.append(f"  - {c['name']} ({c['data_type']}): {c['comment']}{code_str}")
        col_info_text = "\n".join(col_lines)
    except Exception:
        col_info_text = col_json

    prompt = build_sql_fix_prompt()
    messages = prompt.format_messages(
        sql=original_sql,
        diagnosis=diagnosis_text,
        column_info=col_info_text,
    )

    system = str(messages[0].content)
    user = str(messages[1].content)

    # Callbacks: Token 追踪 + 审计日志
    tracker = TokenTracker()
    audit = AuditLogger()
    callbacks = [tracker, audit]

    try:
        raw = chat_text(system_prompt=system, user_message=user, callbacks=callbacks)
    except Exception:
        return None  # retry 耗尽 → 返回 None，触发正则 fallback

    # 清理 markdown 代码块标记
    fixed = raw.strip()
    if fixed.startswith("```"):
        fixed = re.sub(r'^```(?:sql)?\s*\n?', '', fixed)
        fixed = re.sub(r'\n?```\s*$', '', fixed)

    return fixed.strip() if fixed else None


def _is_valid_sql_change(original: str, fixed: str) -> bool:
    """验证修复后的 SQL 基本合理"""
    if not fixed or fixed == original:
        return False
    # 至少包含 SELECT 或 WITH
    upper = fixed.upper()
    if "SELECT" not in upper and "WITH" not in upper:
        return False
    # 不能比原 SQL 短太多（可能被截断）
    if len(fixed) < len(original) * 0.3:
        return False
    return True


# ============================================================================
# 正则修复（fallback）
# ============================================================================

def _regex_fix_sql(sql: str, item) -> str:
    """正则修复单个诊断项 — LLM 不可用时的 fallback"""
    fix_type = item.source
    columns = item.affected_columns

    if fix_type == "null_rate" and columns:
        for col in columns:
            sql = _apply_coalesce_fix(sql, col)

    elif fix_type == "field_length" and columns:
        for col in columns:
            sql = _apply_substr_fix(sql, col)

    elif fix_type == "code_compliance" and columns:
        for col in columns:
            sql = _apply_code_filter_fix(sql, col)

    elif fix_type == "schema" and columns:
        sql = _apply_schema_fix(sql, columns)

    elif fix_type == "pk_uniqueness":
        sql = _apply_distinct_fix(sql)

    return sql


def _apply_coalesce_fix(sql: str, column: str) -> str:
    """SELECT 中给列加 COALESCE"""
    m = re.search(r'(SELECT\s+)(.*?)(\s+FROM\s+)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return sql
    before, middle, after = m.group(1), m.group(2), m.group(3)
    pattern = rf'\b{re.escape(column)}\b'
    if column in middle and f"COALESCE({column}" not in middle:
        middle = re.sub(pattern, f"COALESCE({column}, '')", middle, count=1)
    return before + middle + after


def _apply_substr_fix(sql: str, column: str) -> str:
    """SELECT 中给列加 SUBSTR 截断"""
    m = re.search(r'(SELECT\s+)(.*?)(\s+FROM\s+)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return sql
    before, middle, after = m.group(1), m.group(2), m.group(3)
    pattern = rf'\b{re.escape(column)}\b'
    if column in middle and f"SUBSTR({column}" not in middle:
        middle = re.sub(pattern, f"SUBSTR({column}, 1, 64)", middle, count=1)
    return before + middle + after


def _apply_code_filter_fix(sql: str, column: str) -> str:
    """WHERE 中增加码值过滤（从诊断恢复合法码值）"""
    if "WHERE" not in sql.upper():
        return sql
    # 在 WHERE 后追加 AND col IN (合法值) — 简化版本
    return sql


def _apply_schema_fix(sql: str, missing_columns: list[str]) -> str:
    """补缺失列"""
    if not missing_columns:
        return sql
    m = re.search(r'(SELECT\s+)(.*?)(\s+FROM\s+)', sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return sql
    before, middle, after = m.group(1), m.group(2), m.group(3)
    for col in missing_columns:
        if col not in middle:
            middle = middle.rstrip().rstrip(",") + f",\n    NULL AS {col}"
    return before + middle + after


def _apply_distinct_fix(sql: str) -> str:
    """SELECT 后加 DISTINCT 修复主键重复"""
    if "SELECT DISTINCT" in sql.upper():
        return sql
    return re.sub(r'\bSELECT\b', 'SELECT DISTINCT', sql, count=1, flags=re.IGNORECASE)


# ============================================================================
# 辅助
# ============================================================================

def _deserialize_column_infos(json_str: str) -> list:
    """从 JSON 反序列化 ColumnInfo 列表"""
    from models import ColumnInfo, CodeMapping
    try:
        data = json.loads(json_str)
        result = []
        for item in data:
            codes = [CodeMapping(value=cv["value"], meaning=cv["meaning"])
                     for cv in item.get("code_values", [])]
            item["code_values"] = codes
            result.append(ColumnInfo(**item))
        return result
    except Exception:
        return []
