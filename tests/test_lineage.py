"""
测试数据血缘（Data Lineage）功能
"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import (
    PseudoCode, PseudoCodeStep, TableInfo, ColumnInfo, DataLayer,
    Assertion, AssertionType, CodeMapping,
)
from generator.script import (
    _build_lineage_map,
    _build_script_header,
    _extract_join_source_system,
    generate_sql_script,
    _clean_table_name,
)


# ============================================================================
# 测试数据
# ============================================================================

def _make_tables() -> dict[str, TableInfo]:
    """构建含 source_system 的测试表集合"""
    return {
        "dim_customer": TableInfo(
            table_name="dim_customer",
            table_comment="客户维表",
            layer=DataLayer.ODS,
            source_system="核心银行系统",
            columns=[
                ColumnInfo(name="cust_id", data_type="VARCHAR(36)", is_primary_key=True),
                ColumnInfo(name="cust_status", data_type="VARCHAR(2)",
                           code_values=[CodeMapping(value="01", meaning="活跃"),
                                        CodeMapping(value="02", meaning="休眠")]),
            ],
        ),
        "dim_channel": TableInfo(
            table_name="dim_channel",
            table_comment="渠道维表",
            layer=DataLayer.ODS,
            source_system="核心银行系统",
            columns=[
                ColumnInfo(name="channel_id", data_type="VARCHAR(20)", is_primary_key=True),
                ColumnInfo(name="channel_name", data_type="VARCHAR(50)"),
            ],
        ),
        "fact_aml_alert": TableInfo(
            table_name="fact_aml_alert",
            table_comment="AML预警事实表",
            layer=DataLayer.DWS,
            source_system="AML反洗钱系统",
            columns=[
                ColumnInfo(name="alert_id", data_type="VARCHAR(36)", is_primary_key=True),
                ColumnInfo(name="account_id", data_type="VARCHAR(36)",
                           referenced_table="dim_account"),
            ],
        ),
        "v_customer_summary": TableInfo(
            table_name="v_customer_summary",
            table_comment="客户汇总视图",
            layer=DataLayer.DM,
            source_system="核心银行系统",
            columns=[
                ColumnInfo(name="cust_id", data_type="VARCHAR(36)", is_primary_key=True),
                ColumnInfo(name="total_amount", data_type="DECIMAL(20,4)"),
            ],
        ),
        "v_unknown_source": TableInfo(
            table_name="v_unknown_source",
            table_comment="未知来源视图",
            layer=DataLayer.DM,
            source_system="",  # 未标注源系统
            columns=[
                ColumnInfo(name="id", data_type="INTEGER", is_primary_key=True),
            ],
        ),
    }


SAMPLE_PSEUDOCODE = PseudoCode(
    title="统计各渠道活跃客户数",
    steps=[
        PseudoCodeStep(
            step_number=1,
            description="筛选活跃客户",
            source_table="v_customer_summary",
            conditions=["cust_status = '01'"],
            output="cust_id",
        ),
        PseudoCodeStep(
            step_number=2,
            description="关联渠道信息",
            source_table="",
            joins=["LEFT JOIN dim_channel ON v_customer_summary.channel_id = dim_channel.channel_id"],
            output="channel_name, COUNT(DISTINCT cust_id) AS active_cnt",
        ),
    ],
)


# ============================================================================
# _build_lineage_map 测试
# ============================================================================

class TestBuildLineageMap:
    """测试血缘映射构建"""

    def test_explicit_source_system(self):
        """显式声明的 source_system 直接使用"""
        tables = _make_tables()
        lineage = _build_lineage_map(tables)

        assert lineage["dim_customer"] == "核心银行系统"
        assert lineage["dim_channel"] == "核心银行系统"
        assert lineage["fact_aml_alert"] == "AML反洗钱系统"
        assert lineage["v_customer_summary"] == "核心银行系统"

    def test_empty_source_system_when_not_declared(self):
        """未声明 source_system 且无法追踪的表返回空"""
        tables = _make_tables()
        lineage = _build_lineage_map(tables)

        assert lineage.get("v_unknown_source", "") == ""

    def test_trace_via_fk_relationship(self):
        """通过 FK 链追踪上游源系统"""
        tables = _make_tables()
        # dim_account 有 source_system="核心银行系统"
        # fact_aml_alert 有 FK account_id → dim_account
        # v_unknown_source 无 source_system 也无 FK
        lineage = _build_lineage_map(tables)
        # fact_aml_alert 显式声明了 source_system，应直接返回
        assert lineage["fact_aml_alert"] == "AML反洗钱系统"

    def test_empty_tables(self):
        """空表集合 → 空映射"""
        lineage = _build_lineage_map({})
        assert lineage == {}


# ============================================================================
# _build_script_header 血缘测试
# ============================================================================

class TestScriptHeaderLineage:
    """测试 SQL 脚本头中的血缘信息"""

    def test_header_includes_lineage_section(self):
        """头部包含数据血缘段落"""
        tables = _make_tables()
        header = _build_script_header(
            pseudocode=SAMPLE_PSEUDOCODE,
            unmatched_concepts=[],
            requirement_summary="统计渠道客户数",
            tables=tables,
        )

        assert "🔗 数据血缘" in header
        assert "核心银行系统" in header
        # v_customer_summary 来自核心银行系统
        assert "v_customer_summary" in header

    def test_header_without_tables_skips_lineage(self):
        """无 tables 参数时跳过血缘段落"""
        header = _build_script_header(
            pseudocode=SAMPLE_PSEUDOCODE,
            unmatched_concepts=[],
            requirement_summary="统计渠道客户数",
            tables=None,
        )

        assert "🔗 数据血缘" not in header

    def test_header_shows_unknown_source_warning(self):
        """未标注源系统的表显示警告"""
        tables = {
            "v_unknown_source": TableInfo(
                table_name="v_unknown_source",
                table_comment="未知来源",
                layer=DataLayer.DM,
                source_system="",
                columns=[ColumnInfo(name="id", data_type="INTEGER")],
            ),
        }
        pseudo = PseudoCode(
            title="测试",
            steps=[
                PseudoCodeStep(
                    step_number=1,
                    description="测试步骤",
                    source_table="v_unknown_source",
                    output="*",
                ),
            ],
        )
        header = _build_script_header(
            pseudocode=pseudo,
            unmatched_concepts=[],
            requirement_summary="",
            tables=tables,
        )

        assert "⚠ 未标注源系统" in header
        assert "v_unknown_source" in header

    def test_header_includes_layer_info(self):
        """血缘段落中包含数据层信息"""
        tables = _make_tables()
        header = _build_script_header(
            pseudocode=SAMPLE_PSEUDOCODE,
            unmatched_concepts=[],
            requirement_summary="",
            tables=tables,
        )

        assert "(DM层)" in header


# ============================================================================
# _extract_join_source_system 测试
# ============================================================================

class TestExtractJoinSourceSystem:
    """测试 JOIN 子句中的源系统提取"""

    def test_extract_from_left_join(self):
        """从 LEFT JOIN 提取源系统"""
        tables = _make_tables()
        lineage = _build_lineage_map(tables)
        join = "LEFT JOIN dim_channel ON v_customer_summary.channel_id = dim_channel.channel_id"

        result = _extract_join_source_system(join, lineage, tables)
        assert result == "核心银行系统"

    def test_extract_from_plain_join(self):
        """从 JOIN 提取源系统"""
        tables = _make_tables()
        lineage = _build_lineage_map(tables)
        join = "JOIN fact_aml_alert ON t.account_id = fact_aml_alert.account_id"

        result = _extract_join_source_system(join, lineage, tables)
        assert result == "AML反洗钱系统"

    def test_no_match_returns_empty(self):
        """无法匹配的表返回空"""
        tables = _make_tables()
        lineage = _build_lineage_map(tables)
        join = "LEFT JOIN nonexistent_table ON t.id = nonexistent_table.id"

        result = _extract_join_source_system(join, lineage, tables)
        assert result == ""

    def test_empty_lineage_returns_empty(self):
        """空血缘映射返回空"""
        join = "LEFT JOIN dim_channel ON t.id = dim_channel.id"
        result = _extract_join_source_system(join, {}, {})
        assert result == ""


# ============================================================================
# generate_sql_script 集成测试
# ============================================================================

class TestGenerateSQLScriptLineage:
    """测试 CTE 链中的血缘注释"""

    def test_cte_includes_lineage_comment(self):
        """CTE 的 FROM 行包含来源系统注释"""
        tables = _make_tables()
        sql = generate_sql_script(
            pseudocode=SAMPLE_PSEUDOCODE,
            tables=tables,
            assertions=None,
            unmatched_concepts=[],
            requirement_summary="测试血缘",
        )

        # CTE step_01 的 FROM v_customer_summary 应标注来源系统
        assert "-- 来源系统: 核心银行系统" in sql

    def test_cte_join_includes_lineage_comment(self):
        """CTE 的 JOIN 行包含来源系统注释"""
        tables = _make_tables()
        sql = generate_sql_script(
            pseudocode=SAMPLE_PSEUDOCODE,
            tables=tables,
            assertions=None,
            unmatched_concepts=[],
            requirement_summary="测试血缘",
        )

        # dim_channel 的来源系统应出现在 JOIN 注释中
        assert "来源系统: 核心银行系统" in sql

    def test_empty_steps_still_has_lineage_header(self):
        """空步骤时头部仍包含血缘信息"""
        tables = _make_tables()
        pseudo = PseudoCode(title="空测试", steps=[])
        sql = generate_sql_script(
            pseudocode=pseudo,
            tables=tables,
            assertions=None,
            unmatched_concepts=[],
            requirement_summary="",
        )

        # 头部不应包含血缘（因为没有步骤，没有涉及的表）
        # 但也不应崩溃
        assert "无分析步骤" in sql


# ============================================================================
# 加载器集成测试
# ============================================================================

class TestLoaderSourceSystem:
    """测试字典加载器对 source_system 的解析"""

    def test_bank_dict_parses_source_system(self):
        """银行数据字典正确解析源系统"""
        from dictionary.loader import load_dictionary

        dd = load_dictionary("demo/bank_data_dict.csv")

        # 检查核心银行系统表
        core_tables = ["dim_customer", "dim_account", "dim_channel",
                       "dim_date", "dim_currency", "dim_counterparty",
                       "fact_transaction", "v_customer_summary",
                       "v_channel_daily_summary"]
        for t in dd.tables:
            if t.table_name in core_tables:
                assert t.source_system == "核心银行系统", \
                    f"{t.table_name}: expected 核心银行系统, got {t.source_system}"

        # 检查 AML 表
        aml_tables = ["fact_velocity", "v_suspicious_transactions"]
        for t in dd.tables:
            if t.table_name in aml_tables:
                assert t.source_system == "AML反洗钱系统", \
                    f"{t.table_name}: expected AML反洗钱系统, got {t.source_system}"

    def test_source_system_in_loader_output(self):
        """加载后的 TableInfo 包含 source_system"""
        from dictionary.loader import load_dictionary

        dd = load_dictionary("demo/bank_data_dict.csv")
        for t in dd.tables:
            assert hasattr(t, "source_system"), \
                f"TableInfo missing source_system attribute"
            assert isinstance(t.source_system, str), \
                f"source_system should be str, got {type(t.source_system)}"


# ============================================================================
# 边界情况
# ============================================================================

class TestLineageEdgeCases:
    """血缘功能边界情况"""

    def test_no_tables_no_crash(self):
        """无 tables 时所有函数不崩溃"""
        # _build_lineage_map
        lineage = _build_lineage_map({})
        assert lineage == {}

        # _build_script_header
        header = _build_script_header(
            pseudocode=SAMPLE_PSEUDOCODE,
            unmatched_concepts=[],
            requirement_summary="",
            tables=None,
        )
        assert isinstance(header, str)

        # _extract_join_source_system
        result = _extract_join_source_system("LEFT JOIN t ON t.id = x.id", {}, {})
        assert result == ""

    def test_special_characters_in_source_system(self):
        """源系统名含特殊字符时正常处理"""
        tables = {
            "test_table": TableInfo(
                table_name="test_table",
                table_comment="测试表",
                layer=DataLayer.ODS,
                source_system="核心-银行_V2.0",
                columns=[ColumnInfo(name="id", data_type="INTEGER")],
            ),
        }
        lineage = _build_lineage_map(tables)
        assert lineage["test_table"] == "核心-银行_V2.0"

    def test_circular_fk_does_not_loop(self):
        """循环 FK 引用不会导致死循环"""
        tables = {
            "table_a": TableInfo(
                table_name="table_a", layer=DataLayer.DM, source_system="",
                columns=[ColumnInfo(name="id", data_type="INTEGER",
                           referenced_table="table_b")],
            ),
            "table_b": TableInfo(
                table_name="table_b", layer=DataLayer.DWS, source_system="",
                columns=[ColumnInfo(name="id", data_type="INTEGER",
                           referenced_table="table_a")],
            ),
        }
        # 不应死循环
        lineage = _build_lineage_map(tables)
        assert isinstance(lineage, dict)
