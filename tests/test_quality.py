"""
L1 数据质量检查 — SQL 生成模式测试
用 sqlite3 内存库端到端验证：建表 → 生成测试SQL → 执行 → 解析结果
"""
import pytest
import sqlite3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import ColumnInfo, CodeMapping
from testing.quality import (
    QualityCheckResult,
    QualityReport,
    wrap_as_cte,
    generate_pk_uniqueness_sql,
    generate_null_rate_sql,
    generate_field_length_sql,
    generate_code_compliance_sql,
    generate_all_checks_sql,
    generate_row_count_sql,
    parse_test_results,
    run_quality_tests,
    check_cartesian_product,
    _parse_max_length,
)
from testing.comparison import compare_schema as _compare_schema


# ============================================================================
# Fixtures
# ============================================================================

SAMPLE_COLUMNS = [
    ColumnInfo(name="cust_id", data_type="varchar(32)", comment="客户编号", is_primary_key=True),
    ColumnInfo(name="cust_name", data_type="varchar(64)", comment="客户名称"),
    ColumnInfo(name="cust_status", data_type="varchar(2)", comment="客户状态",
               code_values=[
                   CodeMapping(value="01", meaning="活跃"),
                   CodeMapping(value="02", meaning="休眠"),
                   CodeMapping(value="03", meaning="销户"),
               ]),
    ColumnInfo(name="channel_id", data_type="varchar(16)", comment="渠道编号"),
]

ORIGINAL_SQL = "SELECT cust_id, cust_name, cust_status, channel_id FROM _test_data"


@pytest.fixture
def conn():
    """sqlite3 内存库，预置测试数据"""
    c = sqlite3.connect(":memory:")
    c.execute("""
        CREATE TABLE _test_data (
            cust_id TEXT, cust_name TEXT, cust_status TEXT, channel_id TEXT
        )
    """)
    c.executemany(
        "INSERT INTO _test_data VALUES (?, ?, ?, ?)",
        [
            ("C001", "张三", "01", "CH01"),
            ("C002", "李四", "01", "CH02"),
            ("C003", None,   "02", "CH01"),
            ("C004", "王五", "99", "CH03"),
            ("C005", "",     "01", None),
        ],
    )
    c.commit()
    return c


@pytest.fixture
def clean_conn():
    """空数据库"""
    return sqlite3.connect(":memory:")


# ============================================================================
# CTE 包装
# ============================================================================

class TestWrapAsCte:
    def test_basic_wrap(self):
        result = wrap_as_cte("SELECT 1")
        assert "WITH _source AS" in result
        assert "SELECT 1" in result

    def test_strips_semicolon(self):
        result = wrap_as_cte("SELECT 1;")
        assert ";" not in result.split("SELECT 1")[-1]


# ============================================================================
# SQL 生成
# ============================================================================

class TestGeneratePkUniquenessSQL:
    def test_generates_valid_sql(self, conn):
        sql = generate_pk_uniqueness_sql(ORIGINAL_SQL, ["cust_id"])
        rows = conn.execute(sql).fetchall()
        assert len(rows) == 0  # 5 行全部唯一

    def test_detects_duplicate(self, conn):
        conn.execute("INSERT INTO _test_data VALUES ('C001', 'dup', '01', 'CH01')")
        sql = generate_pk_uniqueness_sql(ORIGINAL_SQL, ["cust_id"])
        rows = conn.execute(sql).fetchall()
        assert len(rows) >= 1
        assert rows[0][0] == "pk_uniqueness"

    def test_empty_pk_returns_empty(self):
        assert generate_pk_uniqueness_sql(ORIGINAL_SQL, []) == ""

    def test_composite_key(self, conn):
        sql = generate_pk_uniqueness_sql(ORIGINAL_SQL, ["cust_id", "cust_status"])
        rows = conn.execute(sql).fetchall()
        assert len(rows) == 0  # 无重复


class TestGenerateNullRateSQL:
    def test_generates_valid_sql(self, conn):
        sql = generate_null_rate_sql(ORIGINAL_SQL, ["cust_id", "cust_name", "cust_status"])
        rows = conn.execute(sql).fetchall()
        assert len(rows) == 3  # 每列一行

    def test_detects_nulls(self, conn):
        sql = generate_null_rate_sql(ORIGINAL_SQL, ["cust_name"])
        rows = conn.execute(sql).fetchall()
        # 第3行 None，第5行 "" → 2/5 = 40%
        # 统一 schema: (check_type, col_name, total, null_count, null_pct)
        assert int(rows[0][3] or 0) >= 1  # null_count >= 1
        assert float(rows[0][4] or 0) > 0  # null_rate_pct > 0

    def test_empty_columns(self):
        assert generate_null_rate_sql(ORIGINAL_SQL, []) == ""


class TestGenerateFieldLengthSQL:
    def test_generates_valid_sql(self, conn):
        sql = generate_field_length_sql(ORIGINAL_SQL, SAMPLE_COLUMNS)
        rows = conn.execute(sql).fetchall()
        # 没有超长数据
        assert len(rows) == 0

    def test_detects_overlength(self, conn):
        conn.execute("INSERT INTO _test_data VALUES ('C006', ? || ? || ?, '01', 'CH01')",
                     ('A', 'A', 'A' * 98))
        conn.commit()
        sql = generate_field_length_sql(ORIGINAL_SQL, SAMPLE_COLUMNS)
        rows = conn.execute(sql).fetchall()
        assert len(rows) >= 1, f"Expected >=1 rows, got {len(rows)}"
        assert rows[0][0] == "field_length"

    def test_skips_non_string(self):
        cols = [ColumnInfo(name="amount", data_type="decimal(18,2)")]
        sql = generate_field_length_sql(ORIGINAL_SQL, cols)
        assert sql == ""


class TestGenerateCodeComplianceSQL:
    def test_valid_codes(self, conn):
        sql = generate_code_compliance_sql(ORIGINAL_SQL, "cust_status", ["01", "02", "03"])
        rows = conn.execute(sql).fetchall()
        # 第4行 cust_status="99" → 非法
        assert len(rows) >= 1
        assert rows[0][0] == "code_compliance"
        assert "99" in str(rows[0][2])

    def test_all_valid(self, conn):
        # 只保留合法码值的数据
        conn.execute("DELETE FROM _test_data WHERE cust_status = '99'")
        sql = generate_code_compliance_sql(ORIGINAL_SQL, "cust_status", ["01", "02", "03"])
        rows = conn.execute(sql).fetchall()
        assert len(rows) == 0

    def test_empty_codes(self):
        assert generate_code_compliance_sql(ORIGINAL_SQL, "status", []) == ""


# ============================================================================
# 聚合生成
# ============================================================================

class TestGenerateAllChecksSQL:
    def test_produces_executable_sql(self, conn):
        sql = generate_all_checks_sql(ORIGINAL_SQL, SAMPLE_COLUMNS)
        rows = conn.execute(sql).fetchall()
        assert len(rows) > 0  # 至少有空值检查和码值检查的结果

    def test_includes_all_check_types(self, conn):
        sql = generate_all_checks_sql(ORIGINAL_SQL, SAMPLE_COLUMNS)
        rows = conn.execute(sql).fetchall()
        types = {r[0] for r in rows}
        assert "null_rate" in types
        assert "code_compliance" in types  # cust_status 有码值定义

    def test_respects_disable_code_check(self, conn):
        sql = generate_all_checks_sql(ORIGINAL_SQL, SAMPLE_COLUMNS, check_code_values=False)
        rows = conn.execute(sql).fetchall()
        types = {r[0] for r in rows}
        assert "code_compliance" not in types

    def test_no_columns_produces_message(self):
        sql = generate_all_checks_sql(ORIGINAL_SQL, [])
        assert "无需检查" in sql


# ============================================================================
# 结果解析
# ============================================================================

class TestParseTestResults:
    def test_parses_null_rate(self, conn):
        sql = generate_null_rate_sql(ORIGINAL_SQL, ["cust_name"])
        rows = conn.execute(sql).fetchall()
        report = parse_test_results(rows, SAMPLE_COLUMNS, max_null_rate=0.10)
        # cust_name 空值率 40% > 10% → failed
        null_checks = [c for c in report.checks if c.check_type == "null_rate" and c.column == "cust_name"]
        assert null_checks[0].passed is False

    def test_all_pass_with_clean_data(self, conn):
        conn.execute("DELETE FROM _test_data")
        conn.execute("INSERT INTO _test_data VALUES ('C001', '张三', '01', 'CH01')")
        conn.execute("INSERT INTO _test_data VALUES ('C002', '李四', '02', 'CH02')")

        sql = generate_all_checks_sql(ORIGINAL_SQL, SAMPLE_COLUMNS)
        rows = conn.execute(sql).fetchall()
        report = parse_test_results(rows, SAMPLE_COLUMNS)
        assert report.overall_passed is True

    def test_marks_pk_failure(self):
        # 模拟重复主键结果
        rows = [("pk_uniqueness", "C001", "C001", 2)]
        report = parse_test_results(rows, SAMPLE_COLUMNS)
        pk = next(c for c in report.checks if c.check_type == "pk_uniqueness")
        assert pk.passed is False

    def test_code_compliance_failure(self, conn):
        sql = generate_code_compliance_sql(ORIGINAL_SQL, "cust_status", ["01", "02", "03"])
        rows = conn.execute(sql).fetchall()
        report = parse_test_results(rows, SAMPLE_COLUMNS)
        code = next(c for c in report.checks if c.check_type == "code_compliance" and c.column == "cust_status")
        assert code.passed is False
        assert "99" in code.actual_value


# ============================================================================
# 端到端 run_quality_tests
# ============================================================================

class TestRunQualityTests:
    def test_end_to_end(self, conn):
        report = run_quality_tests(conn, ORIGINAL_SQL, SAMPLE_COLUMNS)
        assert isinstance(report, QualityReport)
        assert report.total_rows == 5
        assert report.total_columns == 4

    def test_detects_issues(self, conn):
        """真实数据有问题 → overall_passed=False"""
        report = run_quality_tests(conn, ORIGINAL_SQL, SAMPLE_COLUMNS)
        assert report.overall_passed is False
        assert report.failed_count > 0

    def test_clean_data_passes(self, conn):
        conn.execute("DELETE FROM _test_data")
        conn.execute("INSERT INTO _test_data VALUES ('C001', '张三', '01', 'CH01')")
        conn.execute("INSERT INTO _test_data VALUES ('C002', '李四', '02', 'CH02')")
        report = run_quality_tests(conn, ORIGINAL_SQL, SAMPLE_COLUMNS)
        assert report.overall_passed is True

    def test_bad_sql_returns_error(self, clean_conn):
        """原始 SQL 本身有语法错误时优雅处理"""
        report = run_quality_tests(clean_conn, "SELECT * FROM nonexistent_table", SAMPLE_COLUMNS)
        assert report.overall_passed is False
        assert any("执行失败" in c.detail for c in report.checks)


# ============================================================================
# 笛卡尔积（元数据检查，不查数据）
# ============================================================================

class TestCartesianProduct:
    def test_exact_product(self):
        result = check_cartesian_product(20000, {"t1": 100, "t2": 200})
        assert result.passed is False
        assert "精确笛卡尔积" in result.detail

    def test_normal(self):
        result = check_cartesian_product(1000, {"customers": 1000})
        assert result.passed is True

    def test_bloat(self):
        result = check_cartesian_product(100000, {"t1": 1000}, max_bloat_ratio=5.0)
        assert result.passed is False

    def test_isolated_table(self):
        result = check_cartesian_product(
            5000, {"t1": 100, "t2": 50, "t3": 20},
            join_pairs=[("t1", "t2")],
        )
        assert result.passed is False

    def test_empty_counts(self):
        result = check_cartesian_product(100, {})
        assert result.passed is True
        assert "跳过" in result.detail


# ============================================================================
# 工具函数
# ============================================================================

class TestParseMaxLength:
    def test_varchar(self):
        assert _parse_max_length("varchar(32)") == 32

    def test_char(self):
        assert _parse_max_length("char(10)") == 10

    def test_decimal_skipped(self):
        assert _parse_max_length("decimal(18,2)") is None

    def test_int_skipped(self):
        assert _parse_max_length("int") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
