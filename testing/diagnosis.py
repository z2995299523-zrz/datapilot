"""
L3 诊断引擎 — LLM 驱动的根因分析与修复建议

五级诊断链路：
  1. 症状识别 — 解析 QualityReport + ComparisonReport，列出所有失败项
  2. 根因定位 — LLM 分析失败模式，推断根因（SQL 逻辑错？数据源脏？JOIN 条件缺失？）
  3. 影响评估 — 评估失败对下游的影响范围
  4. 修复建议 — 给出具体的修复方案（改 SQL WHERE 条件？补码值？加 JOIN？）
  5. 预防措施 — 建议如何避免同类问题

两套实现：
  - diagnose():         LLM 诊断（需要 DEEPSEEK_API_KEY）
  - diagnose_heuristic(): 规则诊断（纯 Python，不调 LLM，即时给出建议）

设计原则：
  - 输入是 L1/L2 的报告 + 原始伪代码/需求
  - 输出是结构化的 DiagnosisReport，供 LangGraph 修复闭环使用
  - 规则诊断总是可用，LLM 诊断更深入但依赖外部调用
"""
import json

from pydantic import BaseModel, Field

from models import DiagnosisRule
from testing.quality import QualityCheckResult, QualityReport
from testing.comparison import ComparisonResult, ComparisonReport


# ============================================================================
# 诊断结果模型
# ============================================================================

class Severity(str):
    CRITICAL = "critical"   # 数据完全不可用（如笛卡尔积）
    HIGH = "high"           # 重要指标差异（如聚合不一致）
    MEDIUM = "medium"       # 部分数据问题（如空值率偏高）
    LOW = "low"             # 微小偏差（如个别码值不合规）


class DiagnosisItem(BaseModel):
    """单条诊断"""
    severity: str = Severity.MEDIUM
    source: str = ""                       # 来源检查（pk_uniqueness / null_rate / aggregation / ...）
    symptom: str = ""                      # 症状描述
    root_cause: str = ""                   # 根因分析
    impact: str = ""                       # 影响评估
    fix_suggestion: str = ""               # 修复建议
    prevention: str = ""                   # 预防措施
    affected_columns: list[str] = Field(default_factory=list)
    is_auto_fixable: bool = False          # 是否可自动修复
    fix_level: str = ""                    # "syntax" | "semantic" | ""


class DiagnosisReport(BaseModel):
    """L3 诊断报告"""
    total_checks: int = 0
    total_failures: int = 0
    items: list[DiagnosisItem] = Field(default_factory=list)
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    auto_fixable_count: int = 0
    summary: str = ""

    def model_post_init(self, __context):
        self.total_failures = len(self.items)
        for item in self.items:
            setattr(self, f"{item.severity}_count", getattr(self, f"{item.severity}_count") + 1)
            if item.is_auto_fixable:
                self.auto_fixable_count += 1


# ============================================================================
# 规则诊断（纯 Python，不调 LLM）
# ============================================================================

# 诊断规则表 — 类型化 DiagnosisRule 列表
DIAGNOSIS_RULES: dict[str, DiagnosisRule] = {
    rule.check_type: rule
    for rule in [
        DiagnosisRule(
            check_type="cartesian_product",
            severity=Severity.CRITICAL,
            symptom="结果集行数异常膨胀，疑似笛卡尔积",
            root_cause="多表 JOIN 时缺少有效的 ON 条件，导致行数 = 各表行数之积。常见于："
                       "1) LEFT JOIN 忘了写 ON；2) ON 条件中关联键名写错；"
                       "3) 数据字典中外键关系标注缺失",
            fix="1) 检查每个 JOIN 子句是否都有 ON 条件；2) 验证关联键名在两个表中是否一致；"
                "3) 补充数据字典中外键引用关系",
            prevention="在 script.py 生成 SQL 时强制校验：每出现一个 JOIN 关键字，"
                       "必须紧跟 ON 条件，否则拒绝生成",
            auto_fixable=False,
            fix_level="semantic",
        ),
        DiagnosisRule(
            check_type="pk_uniqueness",
            severity=Severity.HIGH,
            symptom="主键重复，存在多行相同标识",
            root_cause="1) JOIN 导致行膨胀（最常见）；2) 源表数据本身有重复；"
                       "3) GROUP BY 缺少必要的分组列；4) 窗口函数未正确去重",
            fix="1) 检查 JOIN 条件是否正确；2) 考虑在最外层加 DISTINCT 或 ROW_NUMBER()=1 去重；"
                "3) 检查 GROUP BY 是否包含了所有非聚合 SELECT 列",
            prevention="伪代码生成阶段确认每个 JOIN 的基数关系（1:1, 1:N, N:M），"
                       "对 N:M 关系自动加去重步骤",
            auto_fixable=False,
            fix_level="semantic",
        ),
        DiagnosisRule(
            check_type="null_rate",
            severity=Severity.MEDIUM,
            symptom="列空值率超过阈值",
            root_cause="1) LEFT JOIN 右表无匹配（最常见）；2) 源表数据缺失；"
                       "3) 过滤条件过严导致部分行为 NULL；4) 聚合时未处理 NULL",
            fix="1) 将 LEFT JOIN 改为 INNER JOIN（如果业务允许）；"
                "2) 用 COALESCE(col, default_value) 填充默认值；"
                "3) 在 WHERE 中加 col IS NOT NULL 过滤",
            prevention="伪代码生成时对可能为 NULL 的列标注，输出阶段自动加 COALESCE",
            auto_fixable=True,
        ),
        DiagnosisRule(
            check_type="field_length",
            severity=Severity.LOW,
            symptom="字段值超过数据字典定义的最大长度",
            root_cause="1) 源系统数据质量问题；2) 数据字典维护不及时（定义长度偏小）；"
                       "3) 字符串拼接导致超长（如 CONCAT 多列）",
            fix="1) 更新数据字典中的长度定义；2) 输出时用 SUBSTR(col, 1, N) 截断；"
                "3) 排查源系统数据录入问题",
            prevention="定期比对源表实际数据长度与字典定义，自动告警偏差",
            auto_fixable=True,
        ),
        DiagnosisRule(
            check_type="code_compliance",
            severity=Severity.MEDIUM,
            symptom="存在不在码值映射范围内的非法枚举值",
            root_cause="1) 源系统新增了码值但数据字典未更新；2) 脏数据（录入错误）；"
                       "3) NULL 或空字符串被当作合法值处理",
            fix="1) 更新数据字典码值表；2) 对非法值做映射（如统一归为'其他'）；"
                "3) 在 WHERE 中过滤非法码值",
            prevention="建立码值变更监控：源系统码值表变更时自动同步数据字典",
            auto_fixable=True,
        ),
        DiagnosisRule(
            check_type="row_count",
            severity=Severity.HIGH,
            symptom="结果行数与预期不一致",
            root_cause="1) WHERE 条件过宽或过窄；2) JOIN 导致行数变化；"
                       "3) 聚合逻辑错误；4) 数据源本身发生变化",
            fix="1) 逐层对比中间结果的行数（DM→DWS→ODS）定位偏差层；"
                "2) 检查 WHERE 条件和 JOIN 条件是否正确",
            prevention="伪代码生成时标注每步预期的行数变化方向（↑/↓/=）",
            auto_fixable=False,
            fix_level="semantic",
        ),
        DiagnosisRule(
            check_type="full_diff",
            severity=Severity.HIGH,
            symptom="数据值与预期不一致",
            root_cause="1) SQL 计算逻辑与预期口径不一致；2) 码值转换遗漏；"
                       "3) 浮点数精度问题；4) 时区/字符集问题",
            fix="1) 逐列对比差异，根据差异模式推断错误类型；"
                "2) 对聚合列检查 GROUP BY 是否正确；"
                "3) 检查是否遗漏了码值 JOIN（如 status→status_name 映射）",
            prevention="关键指标列在伪代码中标注计算公式，生成 SQL 后自动校验公式一致性",
            auto_fixable=False,
            fix_level="semantic",
        ),
        DiagnosisRule(
            check_type="aggregation",
            severity=Severity.HIGH,
            symptom="明细聚合值与汇总表不一致",
            root_cause="1) 明细数据与汇总表的数据范围不同（时间窗口/筛选条件差异）；"
                       "2) 聚合使用了不同的去重逻辑；"
                       "3) 汇总表更新不及时（T+1 延迟）",
            fix="1) 对齐明细查询与汇总表的时间范围和筛选条件；"
                "2) 确认 COUNT 与 COUNT(DISTINCT) 的使用是否一致；"
                "3) 检查汇总表的数据时效",
            prevention="在伪代码中显式标注聚合口径（是否去重、是否包含 NULL），生成 SQL 时保持一致",
            auto_fixable=False,
            fix_level="semantic",
        ),
        DiagnosisRule(
            check_type="schema",
            severity=Severity.HIGH,
            symptom="输出列结构与预期不一致",
            root_cause="1) SELECT 列表中列名拼写错误；2) 缺少必要的 JOIN；"
                       "3) 遗漏了需要的列",
            fix="1) 对比预期列和实际列，补充缺失列或移除多余列；"
                "2) 检查伪代码的 output 字段是否完整",
            prevention="在伪代码→SQL 转换时自动校验：所有 output 列都出现在 SELECT 中",
            auto_fixable=True,
            fix_level="syntax",
        ),
    ]
}


def diagnose_heuristic(
    quality_report: QualityReport | None = None,
    comparison_report: ComparisonReport | None = None,
) -> DiagnosisReport:
    """规则诊断 — 纯 Python，不调 LLM

    根据预定义的诊断规则表，将 L1/L2 的失败项映射为诊断条目。

    Args:
        quality_report: L1 质量报告
        comparison_report: L2 比对报告

    Returns:
        DiagnosisReport
    """
    items: list[DiagnosisItem] = []

    # 处理 L1 质量检查失败
    if quality_report:
        for check in quality_report.checks:
            if not check.passed:
                items.append(_apply_rule(check, quality_report))

    # 处理 L2 比对失败
    if comparison_report:
        for check in comparison_report.checks:
            if not check.passed:
                items.append(_apply_rule(check, comparison_report))

    total = (len(quality_report.checks) if quality_report else 0) + \
            (len(comparison_report.checks) if comparison_report else 0)

    report = DiagnosisReport(
        total_checks=total,
        items=items,
    )
    report.summary = _build_summary(report)
    return report


# 未匹配 check_type 时的兜底规则
_FALLBACK_RULE = DiagnosisRule(
    check_type="__fallback__",
    severity=Severity.LOW,
    symptom="检查类型 {check_type} 失败",
    root_cause="未知原因",
    fix="请人工排查",
    prevention="完善该检查项的数据质量规则",
    auto_fixable=False,
)


def _apply_rule(
    check: QualityCheckResult | ComparisonResult,
    report: QualityReport | ComparisonReport,
) -> DiagnosisItem:
    """将单条失败检查映射为诊断条目"""
    rule = DIAGNOSIS_RULES.get(check.check_type, _FALLBACK_RULE)

    # 动态填充 fallback symptom
    symptom = rule.symptom.format(check_type=check.check_type) if rule is _FALLBACK_RULE else rule.symptom

    affected = []
    if hasattr(check, "column") and check.column:
        affected = [check.column] if check.column != "+".join(getattr(check, "column", "").split("+")) \
                  else check.column.split("+")

    return DiagnosisItem(
        severity=rule.severity,
        source=check.check_type,
        symptom=symptom,
        root_cause=rule.root_cause,
        impact=f"影响范围: {', '.join(affected) if affected else '全局'} — {check.detail}",
        fix_suggestion=rule.fix,
        prevention=rule.prevention,
        affected_columns=affected,
        is_auto_fixable=rule.auto_fixable,
        fix_level=rule.fix_level,
    )


def _build_summary(report: DiagnosisReport) -> str:
    """生成诊断摘要"""
    if not report.items:
        return "所有检查通过，无需诊断。"

    parts = []
    if report.critical_count:
        parts.append(f"{report.critical_count} 个严重问题")
    if report.high_count:
        parts.append(f"{report.high_count} 个高优先级问题")
    if report.medium_count:
        parts.append(f"{report.medium_count} 个中等问题")
    if report.low_count:
        parts.append(f"{report.low_count} 个低优先级问题")
    if report.auto_fixable_count:
        parts.append(f"其中 {report.auto_fixable_count} 个可自动修复")

    return "，".join(parts) + "。"


# ============================================================================
# LLM 诊断
# ============================================================================

def diagnose(
    quality_report: QualityReport | None = None,
    comparison_report: ComparisonReport | None = None,
    requirement_text: str = "",
    pseudocode_text: str = "",
    expected_report=None,
) -> DiagnosisReport:
    """LLM 诊断 — LLM 主路径 + 规则引擎 fallback

    流程：
      1. 先跑规则诊断做 baseline（确保始终有结果）
      2. 有失败项时调 LLM 深度分析
      3. Pydantic 校验 LLM 输出
      4. LLM 失败 → 规则诊断结果仍然可用

    Args:
        quality_report: L1 质量报告
        comparison_report: L2 比对报告
        requirement_text: 原始需求文档
        pseudocode_text: 伪代码文本
        expected_report: L2.5 预期比对报告 (ExpectedComparisonReport 或 None)

    Returns:
        DiagnosisReport
    """
    baseline = diagnose_heuristic(quality_report, comparison_report)

    if baseline.total_failures == 0:
        return baseline

    # ── LLM 深度诊断 ──
    try:
        from llm_client import chat_json
        from extractor.prompts import build_diagnosis_prompt
        from models import LLMDiagnosisResponse
        from callbacks.token_tracker import TokenTracker

        context = _build_llm_context(quality_report, comparison_report,
                                     requirement_text, pseudocode_text,
                                     expected_report)

        prompt = build_diagnosis_prompt()
        messages = prompt.format_messages(context=context)
        system = str(messages[0].content)
        user = str(messages[1].content)

        # chat_json 自带 retry + JSON 格式强制
        tracker = TokenTracker()
        raw = chat_json(system_prompt=system, user_message=user, callbacks=[tracker])

        # Pydantic 校验
        llm_response = LLMDiagnosisResponse(**raw)

        # 合并 LLM 结果到 baseline
        for i, item in enumerate(baseline.items):
            if i < len(llm_response.items):
                llm_item = llm_response.items[i]
                # 只覆盖 LLM 提供了更优内容的字段
                if llm_item.root_cause:
                    item.root_cause = llm_item.root_cause
                if llm_item.fix_suggestion:
                    item.fix_suggestion = llm_item.fix_suggestion
                if llm_item.impact:
                    item.impact = llm_item.impact
                if llm_item.prevention:
                    item.prevention = llm_item.prevention
                item.is_auto_fixable = llm_item.is_auto_fixable

    except Exception:
        # LLM 不可用 → 规则引擎结果直接使用（已在 baseline 中）
        pass

    baseline.summary = _build_summary(baseline)
    return baseline


def _build_llm_context(
    quality_report: QualityReport | None,
    comparison_report: ComparisonReport | None,
    requirement_text: str,
    pseudocode_text: str,
    expected_report=None,
) -> str:
    """构建 LLM 诊断的上下文"""
    parts = []

    if requirement_text:
        parts.append(f"## 需求文档\n{requirement_text[:2000]}\n")

    if pseudocode_text:
        parts.append(f"## 伪代码\n{pseudocode_text[:2000]}\n")

    if quality_report:
        parts.append("## L1 数据质量检查结果")
        parts.append(f"总行数: {quality_report.total_rows}")
        parts.append(f"通过: {quality_report.passed_count}, 失败: {quality_report.failed_count}")
        parts.append("")
        for check in quality_report.checks:
            if not check.passed:
                parts.append(f"- [{check.check_type}] {check.column}: {check.detail}")
                parts.append(f"  实际: {check.actual_value} | 期望: {check.expected_value}")
        parts.append("")

    if comparison_report:
        parts.append("## L2 逻辑比对结果")
        parts.append(f"预期行数: {comparison_report.expected_rows}, 实际行数: {comparison_report.actual_rows}")
        parts.append(f"通过: {comparison_report.passed_count}, 失败: {comparison_report.failed_count}")
        parts.append("")
        for check in comparison_report.checks:
            if not check.passed:
                parts.append(f"- [{check.check_type}] {check.detail}")
        parts.append("")

    # ── L2.5 预期结果比对 ──
    if expected_report is not None:
        parts.append("## L2.5 预期结果比对")
        parts.append(f"预期 {expected_report.total_expected} 行, 实际 {expected_report.total_actual} 行")
        parts.append(f"匹配: {expected_report.match_count}, 偏差: {expected_report.mismatch_count}")
        if expected_report.missing_in_actual:
            parts.append(f"缺失行: {', '.join(expected_report.missing_in_actual[:10])}")
        if expected_report.extra_in_actual:
            parts.append(f"多余行: {', '.join(expected_report.extra_in_actual[:10])}")
        if expected_report.value_diffs:
            parts.append("数值偏差详情:")
            for diff in expected_report.value_diffs[:20]:
                parts.append(f"  - {diff.key_values}: {diff.column} "
                           f"预期={diff.expected_value}, 实际={diff.actual_value}, "
                           f"偏差={diff.diff_percent:.1%}")
        parts.append("")

    parts.append("请根据以上信息进行诊断分析，输出 JSON。")
    return "\n".join(parts)
