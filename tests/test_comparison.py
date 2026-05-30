"""
L2 逻辑结果比对 — SQL 生成模式测试
用 sqlite3 内存库端到端验证：建双表 → 生成比对SQL → 执行 → 解析结果
"""
import pytest
import sqlite3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from testing.comparison import (
    ComparisonResult,
    ComparisonReport,
    generate_row_count_compare_sql,
    generate_full_diff_sql,
    generate_aggregation_check_sql,
    compare_schema,
    run_comparison_tests,
)

EXPECTED_SQL = "SELECT * FROM _expected"
ACTUAL_SQL = "SELECT * FROM _actual"
SUMMARY_SQL = "SELECT * FROM _summary"


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def conn():
    """sqlite3 内存库，预置 expected 和 actual 双表"""
    c = sqlite3.connect(":memory:")

    c.execute("CREATE TABLE _expected (id TEXT, name TEXT, amount REAL)")
    c.execute("CREATE TABLE _actual (id TEXT, name TEXT, amount REAL)")

    # 完全一致的数据
    for t in ["_expected", "_actual"]:
        c.executemany(
            f"INSERT INTO {t} VALUES (?, ?, ?)",
            [
                ("1", "张三", 100.0),
                ("2", "李四", 200.0),
                ("3", "王五", 300.0),
            ],
        )

    c.commit()
    return c


@pytest.fixture
def conn_with_diff():
    """expected 和 actual 有差异"""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE _expected (id TEXT, name TEXT, amount REAL)")
    c.execute("CREATE TABLE _actual (id TEXT, name TEXT, amount REAL)")

    c.executemany("INSERT INTO _expected VALUES (?, ?, ?)", [
        ("1", "张三", 100.0),
        ("2", "李四", 200.0),   # id=2 在 actual 中 amount 不同
        ("3", "王五", 300.0),   # id=3 在 actual 中缺失
    ])
    c.executemany("INSERT INTO _actual VALUES (?, ?, ?)", [
        ("1", "张三", 100.0),
        ("2", "李四", 250.0),   # amount 差异
        ("4", "赵六", 400.0),   # 多余行
    ])
    c.commit()
    return c


@pytest.fixture
def conn_aggregation():
    """聚合测试：detail + summary"""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE _actual (channel_id TEXT, amount REAL)")
    c.execute("CREATE TABLE _summary (channel_id TEXT, channel_amount REAL)")

    c.executemany("INSERT INTO _actual VALUES (?, ?)", [
        ("CH01", 100.0), ("CH01", 200.0),
        ("CH02", 150.0), ("CH02", 250.0),
    ])
    c.executemany("INSERT INTO _summary VALUES (?, ?)", [
        ("CH01", 300.0),
        ("CH02", 400.0),
    ])
    c.commit()
    return c


# ============================================================================
# 行数比对
# ============================================================================

class TestRowCountCompare:
    def test_same_count(self, conn):
        sql = generate_row_count_compare_sql(EXPECTED_SQL, ACTUAL_SQL)
        rows = conn.execute(sql).fetchall()
        counts = {r[0]: r[1] for r in rows}
        assert counts["expected"] == counts["actual"] == 3

    def test_different_count(self, conn):
        conn.execute("INSERT INTO _actual VALUES ('5', 'extra', 500.0)")
        sql = generate_row_count_compare_sql(EXPECTED_SQL, ACTUAL_SQL)
        rows = conn.execute(sql).fetchall()
        counts = {r[0]: r[1] for r in rows}
        assert counts["expected"] == 3
        assert counts["actual"] == 4


# ============================================================================
# 全量 diff
# ============================================================================

class TestFullDiffSQL:
    def test_all_match(self, conn):
        sql = generate_full_diff_sql(EXPECTED_SQL, ACTUAL_SQL, ["id"])
        rows = conn.execute(sql).fetchall()
        assert len(rows) == 0  # 无差异

    def test_detects_missing(self, conn_with_diff):
        sql = generate_full_diff_sql(EXPECTED_SQL, ACTUAL_SQL, ["id"])
        rows = conn_with_diff.execute(sql).fetchall()
        types = {r[0] for r in rows}
        assert "missing" in types  # id=3 缺失
        assert "extra" in types    # id=4 多余

    def test_detects_value_diff(self, conn_with_diff):
        sql = generate_full_diff_sql(
            EXPECTED_SQL, ACTUAL_SQL, ["id"],
            compare_columns=["name", "amount"],
        )
        rows = conn_with_diff.execute(sql).fetchall()
        types = {r[0] for r in rows}
        assert "value_diff" in types  # id=2 amount 不同

    def test_with_compare_columns(self, conn_with_diff):
        sql = generate_full_diff_sql(
            EXPECTED_SQL, ACTUAL_SQL, ["id"],
            compare_columns=["amount"],
        )
        rows = conn_with_diff.execute(sql).fetchall()
        # 应有 missing(id=3), extra(id=4), value_diff(id=2 amount=200→250)
        assert len(rows) >= 3


# ============================================================================
# 聚合一致性
# ============================================================================

class TestAggregationCheck:
    def test_consistent(self, conn_aggregation):
        sql = generate_aggregation_check_sql(
            ACTUAL_SQL, SUMMARY_SQL,
            agg_specs=[{
                "group_cols": ["channel_id"],
                "agg_col": "amount",
                "agg_func": "sum",
                "summary_col": "channel_amount",
            }],
        )
        rows = conn_aggregation.execute(sql).fetchall()
        assert len(rows) == 0  # 完全一致

    def test_inconsistent(self, conn_aggregation):
        conn_aggregation.execute("UPDATE _summary SET channel_amount = 299.0 WHERE channel_id = 'CH01'")
        sql = generate_aggregation_check_sql(
            ACTUAL_SQL, SUMMARY_SQL,
            agg_specs=[{
                "group_cols": ["channel_id"],
                "agg_col": "amount",
                "agg_func": "sum",
                "summary_col": "channel_amount",
            }],
        )
        rows = conn_aggregation.execute(sql).fetchall()
        assert len(rows) >= 1
        assert rows[0][0] == "aggregation"

    def test_count_aggregation(self, conn_aggregation):
        conn_aggregation.execute("ALTER TABLE _summary ADD COLUMN channel_count INTEGER")
        conn_aggregation.execute("UPDATE _summary SET channel_count = 2")
        sql = generate_aggregation_check_sql(
            ACTUAL_SQL, SUMMARY_SQL,
            agg_specs=[{
                "group_cols": ["channel_id"],
                "agg_col": "amount",
                "agg_func": "count",
                "summary_col": "channel_count",
            }],
        )
        rows = conn_aggregation.execute(sql).fetchall()
        assert len(rows) == 0  # 2=2


# ============================================================================
# Schema 比对（元数据 → Python）
# ============================================================================

class TestSchema:
    def test_match(self):
        result = compare_schema(["id", "name", "amount"], ["id", "name", "amount"])
        assert result.passed is True

    def test_missing(self):
        result = compare_schema(["id", "name", "amount"], ["id", "name"])
        assert result.passed is False
        assert "amount" in result.detail

    def test_extra(self):
        result = compare_schema(["id", "name"], ["id", "name", "extra"])
        assert result.passed is False


# ============================================================================
# 端到端
# ============================================================================

class TestRunComparisonTests:
    def test_all_match(self, conn):
        report = run_comparison_tests(conn, EXPECTED_SQL, ACTUAL_SQL, key_columns=["id"])
        assert report.overall_passed is True

    def test_with_diffs(self, conn_with_diff):
        report = run_comparison_tests(
            conn_with_diff, EXPECTED_SQL, ACTUAL_SQL,
            key_columns=["id"],
            compare_columns=["amount"],
        )
        assert report.overall_passed is False

    def test_with_aggregation(self, conn_aggregation):
        report = run_comparison_tests(
            conn_aggregation, ACTUAL_SQL, ACTUAL_SQL,
            agg_specs=[{
                "group_cols": ["channel_id"],
                "agg_col": "amount",
                "agg_func": "sum",
                "summary_col": "channel_amount",
            }],
            summary_sql=SUMMARY_SQL,
        )
        assert report.overall_passed is True

    def test_aggregation_failure(self, conn_aggregation):
        conn_aggregation.execute("UPDATE _summary SET channel_amount = 299.0 WHERE channel_id = 'CH01'")
        report = run_comparison_tests(
            conn_aggregation, ACTUAL_SQL, ACTUAL_SQL,
            agg_specs=[{
                "group_cols": ["channel_id"],
                "agg_col": "amount",
                "agg_func": "sum",
                "summary_col": "channel_amount",
            }],
            summary_sql=SUMMARY_SQL,
        )
        assert report.overall_passed is False


# ============================================================================
# 端到端集成: L1+L2
# ============================================================================

class TestL1L2Integration:
    """L1 SQL 生成 + sqlite3 执行 + L2 比对 联合验证"""

    def test_full_pipeline(self):
        """模拟真实场景：原始 SQL → L1 质量 → L2 比对"""
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE orders (id TEXT, product TEXT, qty INTEGER, status TEXT)")
        c.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", [
            ("O001", "产品A", 10, "01"),
            ("O002", "产品B", 20, "01"),
            ("O003", "产品C", None, "99"),  # qty=NULL, status=非法
            ("O001", "产品A", 10, "01"),     # id 重复!
        ])

        from models import ColumnInfo, CodeMapping
        from testing.quality import run_quality_tests
        from testing.comparison import run_comparison_tests

        cols = [
            ColumnInfo(name="id", data_type="varchar(32)", is_primary_key=True),
            ColumnInfo(name="product", data_type="varchar(64)"),
            ColumnInfo(name="qty", data_type="int"),
            ColumnInfo(name="status", data_type="varchar(2)",
                       code_values=[CodeMapping(value="01", meaning="正常"),
                                   CodeMapping(value="02", meaning="取消")]),
        ]

        # L1
        qr = run_quality_tests(c, "SELECT * FROM orders", cols)
        assert qr.overall_passed is False  # 重复+空值+非法码值

        # 验证 SQL 方式的高效：只返回违规行（不是全量 4 行）
        from testing.quality import generate_all_checks_sql
        sql = generate_all_checks_sql("SELECT * FROM orders", cols)
        rows = c.execute(sql).fetchall()
        assert len(rows) < 10  # 违规行数远小于数据总量


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
