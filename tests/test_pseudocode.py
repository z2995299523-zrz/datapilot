"""
测试伪代码生成器
"""
import pytest
import json
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import (
    PseudoCode, PseudoCodeStep, RetrievalResult, TableMatch,
    ColumnMatch, CodeMapping, DataLayer, BusinessConcept, ConceptType,
)
from generator.pseudocode import generate, _format_matches


SAMPLE_PSEUDOCODE_JSON = {
    "title": "统计各渠道近6个月活跃客户数",
    "steps": [
        {
            "step_number": 1,
            "description": "获取活跃客户",
            "source_table": "dm_customer_active",
            "conditions": [
                "cust_status = '01'",
                "last_trans_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)",
            ],
            "joins": [],
            "aggregations": [],
            "output": "cust_id",
        },
        {
            "step_number": 2,
            "description": "关联渠道信息",
            "source_table": "dm_channel_summary",
            "conditions": [],
            "joins": [
                "LEFT JOIN dm_channel_summary ON dm_transaction_daily.channel_id = dm_channel_summary.channel_id"
            ],
            "aggregations": [],
            "output": "channel_type, channel_name",
        },
        {
            "step_number": 3,
            "description": "按渠道聚合统计活跃客户数",
            "source_table": "",
            "conditions": [],
            "joins": [],
            "aggregations": [
                "COUNT(DISTINCT cust_id) AS active_cust_count"
            ],
            "output": "channel_type, active_cust_count",
        },
    ],
    "todo_items": ["待确认数据源 - 账户状态"],
    "notes": ["来自 DM 层", "cust_status 码值: 01=活跃"],
}


@pytest.fixture
def sample_retrieval():
    """构造一个最小检索结果"""
    return RetrievalResult(
        matches=[
            TableMatch(
                concept="活跃客户",
                matched=True,
                layer=DataLayer.DM,
                table_name="dm_customer_active",
                table_comment="活跃客户汇总表",
                score=0.95,
                columns=[
                    ColumnMatch(name="cust_id", comment="客户编号", data_type="varchar(32)"),
                    ColumnMatch(
                        name="cust_status",
                        comment="客户状态",
                        data_type="varchar(2)",
                        code_values=[
                            CodeMapping(value="01", meaning="活跃"),
                            CodeMapping(value="02", meaning="休眠"),
                            CodeMapping(value="03", meaning="销户"),
                        ],
                    ),
                    ColumnMatch(name="last_trans_date", comment="最近交易日期", data_type="date"),
                ],
            ),
            TableMatch(
                concept="渠道",
                matched=True,
                layer=DataLayer.DM,
                table_name="dm_channel_summary",
                table_comment="渠道汇总表",
                score=0.88,
                columns=[
                    ColumnMatch(name="channel_id", comment="渠道编号", data_type="varchar(16)"),
                    ColumnMatch(
                        name="channel_type",
                        comment="渠道类型",
                        data_type="varchar(2)",
                        code_values=[
                            CodeMapping(value="01", meaning="APP"),
                            CodeMapping(value="02", meaning="微信"),
                        ],
                    ),
                ],
            ),
        ],
        unmatched_concepts=["账户状态"],
        retrieval_log=["[DM层] 命中: dm_customer_active", "[DM层] 命中: dm_channel_summary"],
    )


@pytest.fixture
def mock_llm():
    """Mock chat_json，返回预设 dict"""
    with mock.patch("generator.pseudocode.chat_json") as mock_fn:
        mock_fn.return_value = SAMPLE_PSEUDOCODE_JSON
        yield mock_fn


class TestFormatMatches:
    """匹配结果格式化"""

    def test_includes_table_names(self, sample_retrieval):
        text = _format_matches(sample_retrieval)
        assert "dm_customer_active" in text
        assert "dm_channel_summary" in text

    def test_includes_code_values(self, sample_retrieval):
        text = _format_matches(sample_retrieval)
        assert "01=活跃" in text

    def test_includes_unmatched(self, sample_retrieval):
        text = _format_matches(sample_retrieval)
        assert "账户状态" in text

    def test_empty_matches(self):
        result = RetrievalResult()
        text = _format_matches(result)
        assert len(text) > 0


class TestPseudocodeGeneration:
    """伪代码生成"""

    def test_generate_returns_pseudocode(self, sample_retrieval, mock_llm):
        result = generate("统计各渠道活跃客户数", sample_retrieval)
        assert isinstance(result, PseudoCode)
        assert result.title != ""

    def test_generate_has_steps(self, sample_retrieval, mock_llm):
        result = generate("统计各渠道活跃客户数", sample_retrieval)
        assert len(result.steps) == 3
        assert all(isinstance(s, PseudoCodeStep) for s in result.steps)

    def test_step_conditions_preserved(self, sample_retrieval, mock_llm):
        result = generate("test", sample_retrieval)
        step1 = result.steps[0]
        assert any("cust_status" in c for c in step1.conditions)

    def test_todo_items_preserved(self, sample_retrieval, mock_llm):
        result = generate("test", sample_retrieval)
        assert len(result.todo_items) > 0

    def test_notes_preserved(self, sample_retrieval, mock_llm):
        result = generate("test", sample_retrieval)
        assert len(result.notes) > 0

    def test_step_numbers_sequential(self, sample_retrieval, mock_llm):
        result = generate("test", sample_retrieval)
        for i, step in enumerate(result.steps, 1):
            assert step.step_number == i

    def test_source_tables_from_match(self, sample_retrieval, mock_llm):
        result = generate("test", sample_retrieval)
        source_tables = {s.source_table for s in result.steps if s.source_table}
        assert "dm_customer_active" in source_tables
        assert "dm_channel_summary" in source_tables


class TestCliImport:
    """CLI 模块基本导入检查"""

    def test_cli_imports(self):
        import cli
        assert hasattr(cli, "main")
        assert hasattr(cli, "cmd_search")
        assert hasattr(cli, "cmd_analyze")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
