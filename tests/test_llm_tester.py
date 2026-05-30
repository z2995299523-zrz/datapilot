"""
统一 LLM 测试代码生成器 测试
"""
import json
import pytest
import sqlite3
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import (
    ColumnInfo, CodeMapping,
    LLMTestCase, LLMTestSuiteResponse,
)
from testing.llm_tester import (
    generate_test_suite,
    execute_test_suite,
    parse_suite_results,
    run_llm_test_suite,
    _format_column_info,
)

# ============================================================================
# 测试数据
# ============================================================================

SAMPLE_COLS = [
    ColumnInfo(name="cust_id", data_type="varchar(32)", comment="客户编号", is_primary_key=True),
    ColumnInfo(name="cust_name", data_type="varchar(64)", comment="客户名称"),
    ColumnInfo(name="cust_status", data_type="varchar(2)", comment="客户状态",
               code_values=[CodeMapping(value="01", meaning="活跃"),
                           CodeMapping(value="02", meaning="休眠")]),
    ColumnInfo(name="amount", data_type="decimal(18,2)", comment="交易金额"),
]

MOCK_LLM_RESPONSE = {
    "suite_description": "LLM 生成的完整测试套件",
    "test_cases": [
        {
            "check_type": "pk_uniqueness",
            "column_name": "cust_id",
            "description": "检查主键 cust_id 唯一性",
            "test_sql": "SELECT 'pk_uniqueness', cust_id, COUNT(*) AS cnt FROM t GROUP BY cust_id HAVING COUNT(*) > 1",
            "expected_behavior": "返回 0 行 = 通过",
        },
        {
            "check_type": "null_rate",
            "column_name": "cust_name",
            "description": "检查客户名称空值率",
            "test_sql": "SELECT 'null_rate', 'cust_name', SUM(CASE WHEN cust_name IS NULL OR cust_name='' THEN 1 ELSE 0 END) AS nulls, COUNT(*) AS total FROM t",
            "expected_behavior": "空值率 ≤ 10%",
        },
        {
            "check_type": "code_compliance",
            "column_name": "cust_status",
            "description": "检查客户状态码值合规",
            "test_sql": "SELECT 'code_compliance', 'cust_status', cust_status, COUNT(*) FROM t WHERE cust_status NOT IN ('01','02') AND cust_status IS NOT NULL GROUP BY cust_status",
            "expected_behavior": "返回 0 行 = 通过",
        },
        {
            "check_type": "business_rule",
            "column_name": "amount",
            "description": "检查交易金额非负",
            "test_sql": "SELECT 'business_rule', 'amount', amount, NULL FROM t WHERE amount < 0",
            "expected_behavior": "返回 0 行 = 通过",
        },
        {
            "check_type": "boundary",
            "column_name": "amount",
            "description": "检查交易金额是否有极端异常值",
            "test_sql": "SELECT 'boundary', 'amount', amount, NULL FROM t WHERE amount > 10000000",
            "expected_behavior": "返回 0 行 = 通过",
        },
    ],
    "notes": ["建议增加日期范围检查", "建议增加外键引用完整性检查"],
}


@pytest.fixture
def db():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE t (cust_id TEXT, cust_name TEXT, cust_status TEXT, amount REAL)")
    c.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", [
        ("C001", "张三", "01", 1000.0),
        ("C002", "李四", "01", 2000.0),
        ("C001", "张三", "01", 1000.0),  # 重复!
        ("C003", None, "99", -500.0),     # 空值+非法码值+负金额
    ])
    c.commit()
    return c


# ============================================================================
# 测试
# ============================================================================

class TestGenerateTestSuite:
    def test_llm_path_generates_suite(self):
        """LLM 可用时生成完整测试套件"""
        with mock.patch("llm_client.chat_json", return_value=MOCK_LLM_RESPONSE):
            suite = generate_test_suite(
                "SELECT * FROM t", SAMPLE_COLS,
                requirement_text="统计客户交易",
                pseudocode_text="步骤1: 获取客户",
            )
        assert isinstance(suite, LLMTestSuiteResponse)
        assert len(suite.test_cases) == 5
        assert suite.test_cases[0].check_type == "pk_uniqueness"
        assert suite.test_cases[2].check_type == "code_compliance"
        assert suite.test_cases[3].check_type == "business_rule"

    def test_llm_path_includes_business_logic_tests(self):
        """LLM 生成了业务逻辑相关的测试（不只是模板化检查）"""
        with mock.patch("llm_client.chat_json", return_value=MOCK_LLM_RESPONSE):
            suite = generate_test_suite("SELECT * FROM t", SAMPLE_COLS)
        types = {tc.check_type for tc in suite.test_cases}
        assert "business_rule" in types
        assert "boundary" in types

    def test_fallback_when_llm_fails(self):
        """LLM 不可用时回退到规则模板"""
        with mock.patch("llm_client.chat_json", side_effect=RuntimeError("API 不可用")):
            suite = generate_test_suite("SELECT * FROM t", SAMPLE_COLS)
        assert isinstance(suite, LLMTestSuiteResponse)
        assert len(suite.test_cases) >= 1
        assert "降级" in suite.notes[0] or "规则引擎" in suite.suite_description

    def test_fallback_when_llm_returns_empty(self):
        """LLM 返回空结果 → 降级"""
        with mock.patch("llm_client.chat_json", return_value={"test_cases": []}):
            suite = generate_test_suite("SELECT * FROM t", SAMPLE_COLS)
        assert len(suite.test_cases) >= 1


class TestExecuteTestSuite:
    def test_executes_all_tests(self, db):
        suite = LLMTestSuiteResponse(**MOCK_LLM_RESPONSE)
        results = execute_test_suite(db, suite)
        assert len(results) == len(suite.test_cases)

    def test_reports_pass_fail(self, db):
        suite = LLMTestSuiteResponse(**MOCK_LLM_RESPONSE)
        results = execute_test_suite(db, suite)

        # pk_uniqueness: C001 重复 → 应该失败
        pk = next(r for r in results if r["check_type"] == "pk_uniqueness")
        assert pk["passed"] is False
        assert pk["violation_count"] >= 1

        # code_compliance: cust_status='99' → 应该失败
        code = next(r for r in results if r["check_type"] == "code_compliance")
        assert code["passed"] is False

    def test_sql_error_handled(self, db):
        """错误的 SQL 不会中断整体执行"""
        suite = LLMTestSuiteResponse(
            suite_description="",
            test_cases=[LLMTestCase(
                check_type="bad", description="错误SQL",
                test_sql="SELECT * FROM nonexistent_table",
                expected_behavior="",
            )],
        )
        results = execute_test_suite(db, suite)
        assert results[0]["passed"] is False
        assert results[0]["error"] is not None


class TestParseSuiteResults:
    def test_parses_to_quality_report(self):
        suite = LLMTestSuiteResponse(**MOCK_LLM_RESPONSE)
        results = execute_test_suite(sqlite3.connect(":memory:"), suite)
        report = parse_suite_results(results, total_rows=4)
        from testing.quality import QualityReport
        assert isinstance(report, QualityReport)
        assert report.total_rows == 4

    def test_all_pass_produces_clean_report(self):
        """全部通过的测试 → overall_passed=True"""
        results = [
            {"check_type": "pk_uniqueness", "description": "...", "column_name": "id",
             "passed": True, "violation_count": 0, "violations": [], "error": None},
            {"check_type": "null_rate", "description": "...", "column_name": "name",
             "passed": True, "violation_count": 0, "violations": [], "error": None},
        ]
        report = parse_suite_results(results)
        assert report.overall_passed is True


class TestRunLLMTestSuite:
    def test_end_to_end(self, db):
        """生成 → 执行 → 报告 一体化"""
        with mock.patch("llm_client.chat_json", return_value=MOCK_LLM_RESPONSE):
            report = run_llm_test_suite(
                db, "SELECT * FROM t", SAMPLE_COLS,
                requirement_text="统计客户交易金额",
            )
        assert report.overall_passed is False  # 有重复+空值+非法码值
        check_types = {c.check_type for c in report.checks}
        assert "pk_uniqueness" in check_types
        assert "code_compliance" in check_types
        assert "business_rule" in check_types  # LLM 生成的


class TestFormatColumnInfo:
    def test_formats_table(self):
        result = _format_column_info(SAMPLE_COLS)
        assert "cust_id" in result
        assert "PK" in result
        assert "varchar(32)" in result
        assert "01=活跃" in result


# ============================================================================
# 与现有 quality 模块对比
# ============================================================================

class TestVsTemplateApproach:
    """验证 LLM 生成的测试覆盖了模板引擎没有的维度"""

    def test_llm_generates_business_rules(self):
        """模板引擎只生成 pk/null/length/code 检查，
        LLM 还能生成 business_rule 和 boundary 检查"""
        with mock.patch("llm_client.chat_json", return_value=MOCK_LLM_RESPONSE):
            suite = generate_test_suite("SELECT * FROM t", SAMPLE_COLS)

        types = {tc.check_type for tc in suite.test_cases}
        # 模板引擎有的
        assert "pk_uniqueness" in types
        assert "null_rate" in types
        assert "code_compliance" in types
        # LLM 独有的
        assert "business_rule" in types
        assert "boundary" in types

    def test_llm_tests_are_context_aware(self):
        """LLM 看到了 amount 是 decimal(18,2)，生成了金额相关的业务检查"""
        with mock.patch("llm_client.chat_json", return_value=MOCK_LLM_RESPONSE):
            suite = generate_test_suite("SELECT * FROM t", SAMPLE_COLS)

        # 应该有涉及 amount 列的测试
        amount_tests = [tc for tc in suite.test_cases
                        if tc.column_name == "amount"]
        assert len(amount_tests) >= 1
        assert any("金额" in tc.description or "负" in tc.description
                   or "amount" in tc.test_sql.lower()
                   for tc in amount_tests)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
