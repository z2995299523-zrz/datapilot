"""
测试 SQL 脚本生成引擎
"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import (
    PseudoCode, PseudoCodeStep, TableInfo, ColumnInfo, DataLayer,
    Assertion, AssertionType,
)
from generator.script import (
    generate_sql,
    infer_join_keys,
    _parse_output_columns,
    _looks_aggregate,
    _is_aggregated,
    _assertion_already_covered,
)


# ============================================================================
# 测试数据
# ============================================================================

SAMPLE_PSEUDOCODE = PseudoCode(
    title="统计各渠道近6个月活跃客户数",
    steps=[
        PseudoCodeStep(
            step_number=1,
            description="获取活跃客户",
            source_table="dm_customer_active",
            conditions=[
                "cust_status = '01'",
                "last_trans_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)",
            ],
            joins=[],
            aggregations=[],
            output="cust_id",
        ),
        PseudoCodeStep(
            step_number=2,
            description="关联渠道信息",
            source_table="dm_channel_summary",
            conditions=[],
            joins=[
                "LEFT JOIN dm_channel_summary ON dm_customer_active.channel_id = dm_channel_summary.channel_id",
            ],
            aggregations=[],
            output="channel_type, channel_name",
        ),
        PseudoCodeStep(
            step_number=3,
            description="按渠道聚合统计活跃客户数",
            source_table="",
            conditions=[],
            joins=[],
            aggregations=[
                "COUNT(DISTINCT cust_id) AS active_cust_count",
            ],
            output="channel_type, active_cust_count",
        ),
    ],
    todo_items=["待确认数据源 - 账户状态"],
    notes=["来自 DM 层", "cust_status 码值: 01=活跃"],
)

SINGLE_STEP_PSEUDOCODE = PseudoCode(
    title="查询所有活跃客户",
    steps=[
        PseudoCodeStep(
            step_number=1,
            description="筛选活跃客户",
            source_table="dm_customer_active",
            conditions=["cust_status = '01'"],
            joins=[],
            aggregations=[],
            output="cust_id, cust_name, last_trans_date",
        ),
    ],
)

SAMPLE_TABLES = {
    "dm_customer_active": TableInfo(
        table_name="dm_customer_active",
        table_comment="活跃客户汇总表",
        layer=DataLayer.DM,
        columns=[
            ColumnInfo(name="cust_id", comment="客户编号", data_type="varchar(32)", is_primary_key=True),
            ColumnInfo(name="cust_status", comment="客户状态", data_type="varchar(2)"),
            ColumnInfo(name="last_trans_date", comment="最近交易日期", data_type="date"),
            ColumnInfo(name="channel_id", comment="渠道编号", data_type="varchar(16)"),
        ],
    ),
    "dm_channel_summary": TableInfo(
        table_name="dm_channel_summary",
        table_comment="渠道汇总表",
        layer=DataLayer.DM,
        columns=[
            ColumnInfo(name="channel_id", comment="渠道编号", data_type="varchar(16)", is_primary_key=True),
            ColumnInfo(name="channel_type", comment="渠道类型", data_type="varchar(2)"),
            ColumnInfo(name="channel_name", comment="渠道名称", data_type="varchar(32)"),
        ],
    ),
}


# ============================================================================
# 工具函数测试
# ============================================================================

class TestHelpers:
    def test_parse_output_columns(self):
        cols = _parse_output_columns("cust_id, cust_name, last_trans_date")
        assert len(cols) == 3
        assert "cust_id" in cols

    def test_parse_single_column(self):
        cols = _parse_output_columns("cust_id")
        assert cols == ["cust_id"]

    def test_looks_aggregate_count(self):
        assert _looks_aggregate("COUNT(DISTINCT cust_id) AS cnt")

    def test_looks_aggregate_sum(self):
        assert _looks_aggregate("SUM(amount) AS total")

    def test_looks_aggregate_not_aggregate(self):
        assert not _looks_aggregate("cust_id")

    def test_is_aggregated_by_alias(self):
        result = _is_aggregated("active_cust_count", [
            "COUNT(DISTINCT cust_id) AS active_cust_count",
        ])
        assert result is True

    def test_is_not_aggregated(self):
        result = _is_aggregated("channel_type", [
            "COUNT(DISTINCT cust_id) AS active_cust_count",
        ])
        assert result is False


# ============================================================================
# SQL 生成测试
# ============================================================================

class TestGenerateSQL:
    def test_generates_select_from_where(self):
        sql = generate_sql(SINGLE_STEP_PSEUDOCODE, SAMPLE_TABLES)
        assert "SELECT" in sql
        assert "FROM dm_customer_active" in sql
        assert "WHERE" in sql
        assert "cust_status = '01'" in sql

    def test_multi_step_generates_join(self):
        sql = generate_sql(SAMPLE_PSEUDOCODE, SAMPLE_TABLES)
        assert "LEFT JOIN" in sql
        assert "dm_channel_summary" in sql

    def test_aggregation_step_generates_group_by(self):
        sql = generate_sql(SAMPLE_PSEUDOCODE, SAMPLE_TABLES)
        assert "GROUP BY" in sql
        assert "COUNT(DISTINCT cust_id)" in sql

    def test_conditions_in_where_clause(self):
        sql = generate_sql(SAMPLE_PSEUDOCODE, SAMPLE_TABLES)
        assert "cust_status = '01'" in sql
        assert "last_trans_date" in sql

    def test_returns_valid_sql_structure(self):
        sql = generate_sql(SAMPLE_PSEUDOCODE, SAMPLE_TABLES)
        # SQL 以 SELECT 开头
        assert sql.strip().upper().startswith("SELECT")
        # SQL 以换行结尾
        assert sql.endswith("\n")

    def test_empty_steps(self):
        result = generate_sql(PseudoCode())
        assert "无分析步骤" in result

    def test_generates_select_columns(self):
        sql = generate_sql(SINGLE_STEP_PSEUDOCODE, SAMPLE_TABLES)
        assert "cust_id" in sql
        assert "cust_name" in sql

    def test_deduplicates_joins(self):
        """重复 JOIN 去重"""
        p = PseudoCode(
            steps=[
                PseudoCodeStep(
                    step_number=1, description="t1",
                    source_table="dm_customer_active",
                    joins=["LEFT JOIN t2 ON t1.id = t2.id"],
                ),
                PseudoCodeStep(
                    step_number=2, description="t2",
                    source_table="dm_channel_summary",
                    joins=["LEFT JOIN t2 ON t1.id = t2.id"],  # 重复
                ),
            ],
        )
        sql = generate_sql(p)
        assert sql.count("LEFT JOIN t2") == 1

    def test_deduplicates_conditions(self):
        """重复条件去重"""
        p = PseudoCode(
            steps=[
                PseudoCodeStep(
                    step_number=1, description="t1",
                    source_table="dm_customer_active",
                    conditions=["a = 1", "b = 2"],
                ),
                PseudoCodeStep(
                    step_number=2, description="t2",
                    source_table="dm_channel_summary",
                    conditions=["a = 1"],  # 重复
                ),
            ],
        )
        sql = generate_sql(p)
        assert sql.count("a = 1") == 1


# ============================================================================
# JOIN 键推断测试
# ============================================================================

class TestJoinInference:
    def test_infer_by_common_column(self):
        keys = infer_join_keys(
            "dm_customer_active", "dm_channel_summary", SAMPLE_TABLES
        )
        assert len(keys) >= 1
        # 两个表都有 channel_id
        key_pairs = [(l, r) for l, r in keys]
        assert ("channel_id", "channel_id") in key_pairs

    def test_infer_no_common_columns(self):
        t1 = TableInfo(
            table_name="t1", layer=DataLayer.DM,
            columns=[ColumnInfo(name="a", comment="")],
        )
        t2 = TableInfo(
            table_name="t2", layer=DataLayer.DM,
            columns=[ColumnInfo(name="b", comment="")],
        )
        keys = infer_join_keys("t1", "t2", {"t1": t1, "t2": t2})
        assert keys == []

    def test_infer_nonexistent_table(self):
        keys = infer_join_keys("nonexistent", "dm_channel_summary", SAMPLE_TABLES)
        assert keys == []

    def test_foreign_key_preferred(self):
        """有外键引用时优先使用"""
        t1 = TableInfo(
            table_name="t1", layer=DataLayer.DM,
            columns=[
                ColumnInfo(name="dept_id", comment="部门", is_foreign_key=True, referenced_table="t2"),
                ColumnInfo(name="name", comment="名称"),
            ],
        )
        t2 = TableInfo(
            table_name="t2", layer=DataLayer.DM,
            columns=[
                ColumnInfo(name="dept_id", comment="部门编号", is_primary_key=True),
            ],
        )
        keys = infer_join_keys("t1", "t2", {"t1": t1, "t2": t2})
        assert len(keys) >= 1
        assert keys[0] == ("dept_id", "dept_id")


class TestAssertionAlreadyCovered:
    """_assertion_already_covered — P1 补测"""

    def test_column_and_value_match(self):
        a = Assertion(type=AssertionType.CODE, column="cust_status",
                      value="01", sql_condition="cust_status = '01'")
        assert _assertion_already_covered(a, ["cust_status = '01'"]) is True

    def test_column_match_but_different_value(self):
        """列名相同但值不同 → 应返回 True（'=' 操作符被认为已覆盖）"""
        a = Assertion(type=AssertionType.CODE, column="cust_status",
                      value="01", sql_condition="cust_status = '01'")
        # 现有 WHERE 有相同列名 + '=' 但值不同 → TRUE（不会重复注入）
        assert _assertion_already_covered(a, ["cust_status = '02'"]) is True

    def test_column_not_in_clause(self):
        a = Assertion(type=AssertionType.CODE, column="risk_level",
                      value="03", sql_condition="risk_level = '03'")
        assert _assertion_already_covered(a, ["cust_status = '01'"]) is False

    def test_empty_where_clauses(self):
        a = Assertion(type=AssertionType.CODE, column="status",
                      value="01", sql_condition="status = '01'")
        assert _assertion_already_covered(a, []) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
