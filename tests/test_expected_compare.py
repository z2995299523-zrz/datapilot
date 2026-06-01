"""
测试预期结果比对 — testing/expected_compare.py (L2.5)
"""
import pytest
import tempfile
import os
from pathlib import Path
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import ExpectedComparisonReport, ValueDiff
from testing.expected_compare import (
    compare_with_expected, _infer_key_columns, _infer_compare_columns,
    _build_summary,
)


@pytest.fixture
def expected_csv():
    """创建临时预期 CSV 文件"""
    df = pd.DataFrame({
        "branch_id": ["B001", "B002", "B003"],
        "txn_amount": [1000.0, 2000.0, 3000.0],
        "txn_count": [10, 20, 30],
    })
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    df.to_csv(path, index=False, encoding="utf-8")
    yield path
    os.unlink(path)


class TestExactMatch:
    """完全匹配场景"""

    def test_exact_match(self, expected_csv):
        actual = pd.DataFrame({
            "branch_id": ["B001", "B002", "B003"],
            "txn_amount": [1000.0, 2000.0, 3000.0],
            "txn_count": [10, 20, 30],
        })
        report = compare_with_expected(actual, expected_csv)
        assert report.overall_passed
        assert report.match_count == 3
        assert report.mismatch_count == 0
        assert report.missing_in_actual == []
        assert report.extra_in_actual == []

    def test_exact_match_with_tolerance(self, expected_csv):
        """偏差在 tolerance 内视为匹配"""
        actual = pd.DataFrame({
            "branch_id": ["B001", "B002", "B003"],
            "txn_amount": [1000.01, 2000.00, 2999.99],
            "txn_count": [10, 20, 30],
        })
        report = compare_with_expected(actual, expected_csv, tolerance=0.01)
        assert report.overall_passed  # 0.001% 偏差在 1% tolerance 内


class TestMissingRows:
    """缺失行检测"""

    def test_missing_rows(self, expected_csv):
        actual = pd.DataFrame({
            "branch_id": ["B001", "B003"],
            "txn_amount": [1000.0, 3000.0],
            "txn_count": [10, 30],
        })
        report = compare_with_expected(actual, expected_csv)
        assert not report.overall_passed
        assert "B002" in report.missing_in_actual


class TestExtraRows:
    """多余行检测"""

    def test_extra_rows(self, expected_csv):
        actual = pd.DataFrame({
            "branch_id": ["B001", "B002", "B003", "B004"],
            "txn_amount": [1000.0, 2000.0, 3000.0, 4000.0],
            "txn_count": [10, 20, 30, 40],
        })
        report = compare_with_expected(actual, expected_csv)
        assert not report.overall_passed
        assert "B004" in report.extra_in_actual


class TestValueDeviation:
    """数值偏差检测"""

    def test_value_deviation(self, expected_csv):
        actual = pd.DataFrame({
            "branch_id": ["B001", "B002", "B003"],
            "txn_amount": [700.0, 2000.0, 3000.0],  # B001 偏差 30%
            "txn_count": [10, 20, 30],
        })
        report = compare_with_expected(actual, expected_csv, tolerance=0.01)
        assert not report.overall_passed
        assert len(report.value_diffs) == 1
        assert report.value_diffs[0].key_values == "B001"
        assert report.value_diffs[0].column == "txn_amount"

    def test_tolerance_boundary(self, expected_csv):
        """偏差刚好超过 tolerance 时报告，刚好在 tolerance 内时跳过"""
        actual = pd.DataFrame({
            "branch_id": ["B001"],
            "txn_amount": [1001.0],  # 0.1% 偏差
            "txn_count": [10],
        })
        # tolerance=0.001 (0.1%) → 刚好超标
        report = compare_with_expected(actual, expected_csv, tolerance=0.0005)
        assert not report.overall_passed
        assert len(report.value_diffs) == 1

    def test_tolerance_passes(self, expected_csv):
        """偏差在 tolerance 内 → 通过（提供完整 3 行避免 missing 触发失败）"""
        actual = pd.DataFrame({
            "branch_id": ["B001", "B002", "B003"],
            "txn_amount": [1000.5, 2000.0, 3000.0],  # B001 偏差 0.05%
            "txn_count": [10, 20, 30],
        })
        report = compare_with_expected(actual, expected_csv, tolerance=0.01)
        assert report.overall_passed


class TestHelpers:
    """辅助函数"""

    def test_infer_key_columns(self):
        expected = pd.DataFrame({
            "dept": ["A", "B"],
            "val": [1, 2],
        })
        actual = pd.DataFrame({
            "dept": ["A", "B", "C"],
            "val": [1, 2, 3],
        })
        keys = _infer_key_columns(expected, actual)
        assert "dept" in keys  # 非数值列优先

    def test_infer_compare_columns(self):
        expected = pd.DataFrame({
            "key": ["a", "b"],
            "val1": [1, 2],
            "val2": [3, 4],
        })
        actual = pd.DataFrame({
            "key": ["a", "b"],
            "val1": [1, 2],
            "val2": [3, 5],
        })
        comp = _infer_compare_columns(expected, actual, ["key"])
        assert "val1" in comp
        assert "val2" in comp
        assert "key" not in comp


class TestBuildSummary:
    """_build_summary — P0 补测"""

    def test_all_match(self):
        report = ExpectedComparisonReport(total_expected=5, total_actual=5)
        summary = _build_summary(report)
        assert "完全匹配" in summary

    def test_missing_and_extra(self):
        report = ExpectedComparisonReport(
            total_expected=5, total_actual=6,
            missing_in_actual=["key1"], extra_in_actual=["key2"],
            value_diffs=[],
        )
        summary = _build_summary(report)
        assert "缺失" in summary
        assert "多余" in summary
        assert "5" in summary
        assert "6" in summary

    def test_value_diffs_only(self):
        report = ExpectedComparisonReport(
            total_expected=5, total_actual=5,
            missing_in_actual=[], extra_in_actual=[],
            value_diffs=[ValueDiff(key_values="k1", column="col", expected_value="10", actual_value="7")],
        )
        summary = _build_summary(report)
        assert "数值偏差" in summary


class TestStringColumnComparison:
    """compare_with_expected 字符串列比对 — P1 补测"""

    @pytest.fixture
    def string_csv(self):
        df = pd.DataFrame({
            "dept": ["sales", "marketing", "engineering"],
            "manager": ["Alice", "Bob", "Charlie"],
        })
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        df.to_csv(path, index=False, encoding="utf-8")
        yield path
        os.unlink(path)

    def test_string_match(self, string_csv):
        actual = pd.DataFrame({
            "dept": ["sales", "marketing", "engineering"],
            "manager": ["Alice", "Bob", "Charlie"],
        })
        report = compare_with_expected(actual, string_csv)
        assert report.overall_passed

    def test_string_mismatch(self, string_csv):
        actual = pd.DataFrame({
            "dept": ["sales", "marketing", "engineering"],
            "manager": ["Alice", "Bob", "David"],  # Charlie → David
        })
        # 显式指定键列，确保 manager 是比对列而非键列
        report = compare_with_expected(actual, string_csv, key_columns=["dept"])
        assert not report.overall_passed
        assert len(report.value_diffs) == 1
        assert report.value_diffs[0].expected_value == "Charlie"


class TestZeroValueComparison:
    """compare_with_expected 零值路径 — P1 补测"""

    @pytest.fixture
    def zero_csv(self):
        df = pd.DataFrame({"k": ["a", "b"], "v": [0.0, 100.0]})
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        df.to_csv(path, index=False, encoding="utf-8")
        yield path
        os.unlink(path)

    def test_both_zero(self, zero_csv):
        """预期=0 实际=0 → 跳过（不报差异）"""
        actual = pd.DataFrame({"k": ["a", "b"], "v": [0.0, 100.0]})
        report = compare_with_expected(actual, zero_csv)
        assert report.overall_passed

    def test_expected_zero_actual_nonzero(self, zero_csv):
        """预期=0 实际≠0 → diff_pct=1.0（100%）"""
        actual = pd.DataFrame({"k": ["a", "b"], "v": [5.0, 100.0]})
        report = compare_with_expected(actual, zero_csv)
        assert not report.overall_passed
        diff = [d for d in report.value_diffs if "a" in d.key_values]
        assert len(diff) == 1
        assert diff[0].diff_percent == 1.0


class TestReportFields:
    """报告字段完整性"""

    def test_summary_generated(self, expected_csv):
        actual = pd.DataFrame({
            "branch_id": ["B001"],
            "txn_amount": [700.0],
            "txn_count": [10],
        })
        report = compare_with_expected(actual, expected_csv)
        assert report.summary != ""
        assert "缺失" in report.summary

    def test_report_numbers(self, expected_csv):
        actual = pd.DataFrame({
            "branch_id": ["B001", "B002", "B003"],
            "txn_amount": [1000.0, 2000.0, 3000.0],
            "txn_count": [10, 20, 30],
        })
        report = compare_with_expected(actual, expected_csv)
        assert report.total_expected == 3
        assert report.total_actual == 3
        assert report.match_count == 3


class TestDBIntegration:
    """SQL 执行 + 预期比对 集成测试"""

    def test_sqlite_execute_and_compare(self):
        """在 SQLite 内存库中执行 SQL 并与预期 CSV 比对"""
        import sqlite3
        import tempfile
        import os

        # 1. 创建 SQLite 内存库 + 示例数据
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE customer_summary (
                branch_id TEXT,
                txn_amount REAL,
                txn_count INTEGER
            )
        """)
        conn.execute("INSERT INTO customer_summary VALUES ('B001', 1000.0, 10)")
        conn.execute("INSERT INTO customer_summary VALUES ('B002', 2000.0, 20)")
        conn.execute("INSERT INTO customer_summary VALUES ('B003', 3000.0, 30)")
        conn.commit()

        # 2. 生成预期 CSV
        expected_df = pd.DataFrame({
            "branch_id": ["B001", "B002", "B003"],
            "txn_amount": [1000.0, 2000.0, 3000.0],
            "txn_count": [10, 20, 30],
        })
        fd, expected_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        expected_df.to_csv(expected_path, index=False, encoding="utf-8")

        try:
            # 3. 执行 SQL 获取实际结果
            sql = "SELECT branch_id, txn_amount, txn_count FROM customer_summary ORDER BY branch_id"
            actual_df = pd.read_sql_query(sql, conn)

            # 4. 比对
            report = compare_with_expected(actual_df, expected_path)
            assert report.overall_passed
            assert report.total_expected == 3
            assert report.total_actual == 3
            assert report.match_count == 3
            assert report.mismatch_count == 0
        finally:
            os.unlink(expected_path)
            conn.close()

    def test_sqlite_execute_and_compare_mismatch(self):
        """SQL 执行结果与预期不一致时正确识别差异"""
        import sqlite3
        import tempfile
        import os

        # 实际数据比预期多一行，且 txn_amount 不同
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE customer_summary (
                branch_id TEXT, txn_amount REAL, txn_count INTEGER
            )
        """)
        conn.execute("INSERT INTO customer_summary VALUES ('B001', 1000.0, 10)")
        conn.execute("INSERT INTO customer_summary VALUES ('B002', 2500.0, 20)")  # 预期是 2000
        conn.execute("INSERT INTO customer_summary VALUES ('B004', 4000.0, 40)")  # 预期没有
        conn.commit()

        expected_df = pd.DataFrame({
            "branch_id": ["B001", "B002", "B003"],
            "txn_amount": [1000.0, 2000.0, 3000.0],
            "txn_count": [10, 20, 30],
        })
        fd, expected_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        expected_df.to_csv(expected_path, index=False, encoding="utf-8")

        try:
            sql = "SELECT branch_id, txn_amount, txn_count FROM customer_summary ORDER BY branch_id"
            actual_df = pd.read_sql_query(sql, conn)

            report = compare_with_expected(actual_df, expected_path)
            assert not report.overall_passed
            assert len(report.missing_in_actual) == 1  # B003 缺失
            assert len(report.extra_in_actual) == 1     # B004 多余
            assert len(report.value_diffs) >= 1          # B002 数值偏差
        finally:
            os.unlink(expected_path)
            conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
