"""
L3 诊断引擎测试
"""
import pytest
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import ColumnInfo, CodeMapping
from testing.quality import (
    QualityReport, QualityCheckResult, run_quality_tests,
)
from testing.comparison import (
    ComparisonReport, ComparisonResult, run_comparison_tests,
)
from testing.diagnosis import (
    diagnose_heuristic,
    diagnose,
    DiagnosisItem,
    DiagnosisReport,
    Severity,
    DIAGNOSIS_RULES,
    _apply_rule,
    _build_summary,
)


# ============================================================================
# 测试数据
# ============================================================================

def _make_failed_quality_report() -> QualityReport:
    """造一个有失败项的 L1 报告"""
    return QualityReport(
        total_rows=500,
        total_columns=4,
        checks=[
            QualityCheckResult(
                check_type="pk_uniqueness", column="cust_id",
                passed=False,
                detail="发现 10 行主键重复",
                actual_value="重复组数 3",
                expected_value="500 行全部唯一",
            ),
            QualityCheckResult(
                check_type="null_rate", column="cust_name",
                passed=False,
                detail="空值 50/500 (10.0%)",
                actual_value="10.0%",
                expected_value="≤ 10%",
            ),
            QualityCheckResult(
                check_type="code_compliance", column="cust_status",
                passed=False,
                detail="发现 1 个非法码值",
                actual_value="'99': 5行",
                expected_value="合法码值: ['01', '02', '03']",
            ),
            QualityCheckResult(
                check_type="field_length", column="cust_name",
                passed=True,
                detail="所有值 ≤ 64 字符",
            ),
        ],
    )


def _make_failed_comparison_report() -> ComparisonReport:
    """造一个有失败项的 L2 报告"""
    return ComparisonReport(
        expected_rows=100,
        actual_rows=20000,
        checks=[
            ComparisonResult(
                check_type="row_count",
                passed=False,
                detail="行数不一致: 预期 100 行，实际 20000 行（多 19900 行）",
                actual_value="20000 行",
                expected_value="100 行",
            ),
            ComparisonResult(
                check_type="aggregation",
                passed=False,
                detail="1 处分组聚合不一致",
                actual_value="分组 CH01: 明细sum(amount)=299.0000 ≠ 汇总channel_amount=300.0000",
                expected_value="明细聚合 = 汇总值",
            ),
            ComparisonResult(
                check_type="schema",
                passed=True,
                detail="列结构一致: 4 列",
            ),
        ],
    )


# ============================================================================
# 规则诊断
# ============================================================================

class TestDiagnoseHeuristic:
    def test_all_failures_diagnosed(self):
        report = diagnose_heuristic(
            quality_report=_make_failed_quality_report(),
        )
        assert report.total_failures == 3  # 3 个失败项
        assert len(report.items) == 3

    def test_comparison_failures_diagnosed(self):
        report = diagnose_heuristic(
            comparison_report=_make_failed_comparison_report(),
        )
        assert report.total_failures == 2  # row_count + aggregation

    def test_combined_report(self):
        report = diagnose_heuristic(
            quality_report=_make_failed_quality_report(),
            comparison_report=_make_failed_comparison_report(),
        )
        assert report.total_failures == 5  # 3 + 2

    def test_empty_checks_all_pass(self):
        report = diagnose_heuristic()
        assert report.total_failures == 0
        assert "通过" in report.summary

    def test_critical_severity(self):
        """笛卡尔积 → critical"""
        qr = QualityReport(
            total_rows=0, total_columns=0,
            checks=[
                QualityCheckResult(
                    check_type="cartesian_product", passed=False,
                    detail="检测到精确笛卡尔积",
                    actual_value="实际 20000 = 100×200",
                    expected_value="≤ 100",
                ),
            ],
        )
        report = diagnose_heuristic(quality_report=qr)
        assert report.critical_count == 1
        assert report.items[0].severity == Severity.CRITICAL

    def test_auto_fixable_items_counted(self):
        """空值率 → auto_fixable=True"""
        qr = QualityReport(
            total_rows=100, total_columns=1,
            checks=[
                QualityCheckResult(
                    check_type="null_rate", column="name",
                    passed=False,
                    detail="空值 50/100 (50.0%)",
                    actual_value="50.0%",
                    expected_value="≤ 10%",
                ),
            ],
        )
        report = diagnose_heuristic(quality_report=qr)
        assert report.auto_fixable_count == 1

    def test_diagnosis_item_has_affected_columns(self):
        report = diagnose_heuristic(quality_report=_make_failed_quality_report())
        # pk_uniqueness → affected_columns=["cust_id"]
        pk_item = next(i for i in report.items if i.source == "pk_uniqueness")
        assert "cust_id" in pk_item.affected_columns


# ============================================================================
# 单条诊断
# ============================================================================

class TestApplyRule:
    def test_known_check_type(self):
        check = QualityCheckResult(
            check_type="null_rate", column="cust_name",
            passed=False,
            detail="空值 50/100 (50.0%)",
            actual_value="50.0%",
            expected_value="≤ 10%",
        )
        report = QualityReport(total_rows=100, total_columns=1, checks=[check])
        item = _apply_rule(check, report)
        assert item.severity == Severity.MEDIUM
        assert item.is_auto_fixable is True
        assert "cust_name" in item.affected_columns

    def test_unknown_check_type(self):
        """未知检查类型 → 默认低优先级"""
        check = QualityCheckResult(
            check_type="some_future_check", column="col_x",
            passed=False,
            detail="something wrong",
        )
        report = QualityReport(total_rows=0, total_columns=0, checks=[check])
        item = _apply_rule(check, report)
        assert item.severity == Severity.LOW
        assert "人工排查" in item.fix_suggestion


class TestBuildSummary:
    def test_all_pass(self):
        report = DiagnosisReport(total_checks=10, items=[])
        summary = _build_summary(report)
        assert "通过" in summary

    def test_mixed_severity(self):
        report = DiagnosisReport(
            total_checks=10,
            items=[
                DiagnosisItem(severity=Severity.CRITICAL, source="cartesian_product",
                              symptom="...", root_cause="...", impact="...",
                              fix_suggestion="...", prevention="..."),
                DiagnosisItem(severity=Severity.MEDIUM, source="null_rate",
                              symptom="...", root_cause="...", impact="...",
                              fix_suggestion="...", prevention="..."),
            ],
        )
        summary = _build_summary(report)
        assert "1 个严重问题" in summary
        assert "1 个中等问题" in summary


# ============================================================================
# LLM 诊断
# ============================================================================

class TestDiagnoseLLM:
    def test_no_failures_skips_llm(self):
        """无失败项时不调用 LLM"""
        qr = QualityReport(
            total_rows=10, total_columns=2,
            checks=[
                QualityCheckResult(check_type="pk_uniqueness", passed=True,
                                   detail="全部唯一"),
            ],
        )
        # LLM 不会报错因为不会被调用
        report = diagnose(quality_report=qr)
        assert report.total_failures == 0
        assert "通过" in report.summary

    def test_llm_diagnosis_enhances_baseline(self):
        """LLM 诊断结果覆盖规则诊断的根因和建议"""
        qr = QualityReport(
            total_rows=100, total_columns=1,
            checks=[
                QualityCheckResult(
                    check_type="null_rate", column="cust_name",
                    passed=False,
                    detail="空值 50/100 (50.0%)",
                    actual_value="50.0%",
                    expected_value="≤ 10%",
                ),
            ],
        )
        mock_llm_response = {
            "items": [
                {
                    "severity": "high",
                    "source": "null_rate",
                    "symptom": "...",
                    "root_cause": "LLM 分析: LEFT JOIN dim_customer 时缺少匹配行",
                    "impact": "影响下游客户分析报表",
                    "fix_suggestion": "LLM 建议: 改为 INNER JOIN 或加 COALESCE",
                    "prevention": "伪代码生成时标注 NULL 风险",
                    "affected_columns": ["cust_name"],
                    "is_auto_fixable": True,
                },
            ],
        }
        with mock.patch("llm_client.chat_json", return_value=mock_llm_response):
            report = diagnose(quality_report=qr)
            assert report.total_failures == 1
            item = report.items[0]
            # LLM 的内容覆盖了规则引擎的
            assert "LLM 分析" in item.root_cause
            assert "LLM 建议" in item.fix_suggestion

    def test_llm_failure_falls_back_to_rules(self):
        """LLM 调用失败时规则诊断仍然可用"""
        qr = QualityReport(
            total_rows=100, total_columns=1,
            checks=[
                QualityCheckResult(
                    check_type="null_rate", column="cust_name",
                    passed=False,
                    detail="空值 50/100 (50.0%)",
                    actual_value="50.0%",
                    expected_value="≤ 10%",
                ),
            ],
        )
        with mock.patch("llm_client.chat_json", side_effect=RuntimeError("API 不可用")):
            report = diagnose(quality_report=qr)
            # 仍然有诊断（来自规则引擎）
            assert report.total_failures == 1
            assert report.items[0].source == "null_rate"

    def test_diagnose_with_requirement_context(self):
        """传入需求文档和伪代码上下文"""
        qr = QualityReport(
            total_rows=100, total_columns=1,
            checks=[
                QualityCheckResult(
                    check_type="code_compliance", column="cust_status",
                    passed=False,
                    detail="发现 1 个非法码值",
                    actual_value="'99': 5行",
                    expected_value="合法码值: ['01', '02', '03']",
                ),
            ],
        )
        mock_llm_response = {"items": []}
        with mock.patch("llm_client.chat_json", return_value=mock_llm_response):
            report = diagnose(
                quality_report=qr,
                requirement_text="统计各渠道活跃客户数",
                pseudocode_text="步骤1: 获取活跃客户 WHERE cust_status='01'",
            )
            assert report.total_failures == 1


# ============================================================================
# 诊断规则完整性
# ============================================================================

class TestDiagnosisRules:
    """确保所有 check_type 都有对应的诊断规则"""
    ALL_CHECK_TYPES = {
        "pk_uniqueness", "null_rate", "field_length", "code_compliance",
        "cartesian_product", "row_count", "full_diff", "aggregation", "schema",
    }

    def test_all_rules_defined(self):
        for ct in self.ALL_CHECK_TYPES:
            assert ct in DIAGNOSIS_RULES, f"缺少诊断规则: {ct}"

    def test_all_rules_have_required_fields(self):
        required = {"severity", "symptom", "root_cause", "fix", "prevention", "auto_fixable"}
        for ct, rule in DIAGNOSIS_RULES.items():
            for field in required:
                assert field in rule, f"{ct} 规则缺少字段: {field}"


# ============================================================================
# 端到端诊断
# ============================================================================

class TestEndToEndDiagnosis:
    """L1 → L2 → L3 链路"""

    def test_full_chain(self):
        """模拟完整诊断链路: SQL → L1 SQL检查 → L2 SQL比对 → L3 diagnose"""
        import sqlite3

        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE t (cust_id TEXT, cust_name TEXT, cust_status TEXT, channel_id TEXT)")
        c.execute("CREATE TABLE t_expected (cust_id TEXT, cust_name TEXT, cust_status TEXT)")
        c.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", [
            ("C001", "张三", "01", "CH01"),
            ("C001", "张三", "01", "CH01"),  # 重复
            ("C002", None,    "99", None),   # 空值+非法码值
        ])
        c.executemany("INSERT INTO t_expected VALUES (?, ?, ?)", [
            ("C001", "张三", "01"),
            ("C002", "李四", "02"),
        ])
        c.commit()

        cols = [
            ColumnInfo(name="cust_id", data_type="varchar(32)", is_primary_key=True),
            ColumnInfo(name="cust_name", data_type="varchar(64)"),
            ColumnInfo(name="cust_status", data_type="varchar(2)",
                       code_values=[
                           CodeMapping(value="01", meaning="活跃"),
                           CodeMapping(value="02", meaning="休眠"),
                       ]),
            ColumnInfo(name="channel_id", data_type="varchar(16)"),
        ]

        # L1: SQL 生成 → 执行 → 报告
        qr = run_quality_tests(c, "SELECT * FROM t", cols)
        assert qr.overall_passed is False

        # L2: SQL 比对 → 执行 → 报告
        cr = run_comparison_tests(
            c, "SELECT * FROM t_expected", "SELECT * FROM t",
            key_columns=["cust_id"],
            compare_columns=["cust_name", "cust_status"],
        )
        assert cr.overall_passed is False

        # L3: 诊断
        report = diagnose_heuristic(quality_report=qr, comparison_report=cr)
        assert report.total_failures >= 3

        for item in report.items:
            assert item.symptom
            assert item.root_cause
            assert item.fix_suggestion
            assert item.severity in {Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW}



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
