"""
端到端集成测试 — 全链路 Pipeline 覆盖
"""
import json
import pytest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import (
    BusinessConcept, ConceptType, ConceptExtractionResult,
    PseudoCode, PseudoCodeStep, RetrievalResult,
    TableMatch, ColumnMatch, CodeMapping, DataLayer,
)


# ============================================================================
# Mock data
# ============================================================================

SAMPLE_CONCEPTS = {
    "concepts": [
        {
            "concept": "活跃客户",
            "context": "统计各渠道活跃客户数",
            "type": "entity",
            "candidates": ["有效客户", "活跃用户"],
            "qualifier": "cust_status = '01'",
        },
        {
            "concept": "渠道",
            "context": "按渠道维度分组",
            "type": "dimension",
            "candidates": ["渠道类型"],
            "qualifier": "",
        },
        {
            "concept": "近6个月",
            "context": "近6个月有交易记录",
            "type": "time_range",
            "candidates": ["最近半年"],
            "qualifier": "trans_date >= DATE_SUB(NOW(), INTERVAL 6 MONTH)",
        },
        {
            "concept": "交易金额",
            "context": "分析销售情况中的金额",
            "type": "metric",
            "candidates": ["交易额", "金额"],
            "qualifier": "",
        },
    ]
}

SAMPLE_PSEUDOCODE = {
    "title": "统计各渠道近6个月活跃客户交易金额",
    "steps": [
        {
            "step_number": 1,
            "description": "获取活跃客户",
            "source_table": "dm_customer_active",
            "conditions": ["cust_status = '01'"],
            "joins": [],
            "aggregations": [],
            "output": "cust_id",
        },
        {
            "step_number": 2,
            "description": "关联渠道和交易信息",
            "source_table": "dm_transaction_daily",
            "conditions": ["trans_date >= DATE_SUB(NOW(), INTERVAL 6 MONTH)"],
            "joins": [
                "LEFT JOIN dm_channel_summary ON dm_transaction_daily.channel_id = dm_channel_summary.channel_id"
            ],
            "aggregations": [],
            "output": "channel_type, channel_name",
        },
        {
            "step_number": 3,
            "description": "按渠道聚合交易金额",
            "source_table": "",
            "conditions": [],
            "joins": [],
            "aggregations": ["SUM(txn_amt) AS total_amount"],
            "output": "channel_type, total_amount",
        },
    ],
    "todo_items": [],
    "notes": ["DM 层数据，cust_status 码值: 01=活跃"],
}

SAMPLE_RETRIEVAL = RetrievalResult(
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
                    name="cust_status", comment="客户状态", data_type="varchar(2)",
                    code_values=[
                        CodeMapping(value="01", meaning="活跃"),
                        CodeMapping(value="02", meaning="休眠"),
                    ],
                ),
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
                ColumnMatch(name="channel_type", comment="渠道类型", data_type="varchar(2)"),
            ],
        ),
        TableMatch(
            concept="近6个月",
            matched=True,
            layer=DataLayer.DM,
            table_name="dm_transaction_daily",
            table_comment="交易明细表",
            score=0.90,
            columns=[
                ColumnMatch(name="trans_date", comment="交易日期", data_type="date"),
                ColumnMatch(name="txn_amt", comment="交易金额", data_type="decimal(18,2)"),
            ],
        ),
        TableMatch(
            concept="交易金额",
            matched=True,
            layer=DataLayer.DM,
            table_name="dm_transaction_daily",
            table_comment="交易明细表",
            score=0.92,
            columns=[
                ColumnMatch(name="txn_amt", comment="交易金额", data_type="decimal(18,2)"),
            ],
        ),
    ],
    unmatched_concepts=[],
)


# ============================================================================
# Test helpers
# ============================================================================

def run_full_pipeline(req_text, mock_concepts=None, mock_pseudocode=None,
                      mock_retrieval=None):
    """运行完整链路（mock LLM 调用 + 使用预构造检索结果避免 BGE 导入）"""
    from extractor.concept import extract_concepts
    from generator.pseudocode import generate
    from generator.script import generate_sql
    from extractor.assertions import build_assertions

    if mock_concepts is None:
        mock_concepts = SAMPLE_CONCEPTS
    if mock_pseudocode is None:
        mock_pseudocode = SAMPLE_PSEUDOCODE
    if mock_retrieval is None:
        mock_retrieval = SAMPLE_RETRIEVAL

    # Mock LLM 概念提取
    with mock.patch("extractor.concept.chat_json", return_value=mock_concepts):
        extraction = extract_concepts(req_text)

    # 使用预构造检索结果（避免 BGE 导入 segfault）
    result = mock_retrieval

    # 构建断言
    assertions = build_assertions(extraction.concepts, result)

    # Mock LLM 伪代码生成
    with mock.patch("generator.pseudocode.chat_json", return_value=mock_pseudocode):
        pseudocode = generate(req_text, result, extraction.concepts, assertions)

    # 生成 SQL
    sql = generate_sql(pseudocode, assertions=assertions)

    return extraction, result, assertions, pseudocode, sql


# ============================================================================
# Tests
# ============================================================================

class TestFullPipelineHappyPath:
    """端到端 happy path"""

    def test_pipeline_all_stages_non_empty(self):
        """全链路 5 个阶段都有输出"""
        req = "统计各渠道近6个月活跃客户的交易金额"
        extraction, result, assertions, pseudocode, sql = run_full_pipeline(req)

        # Stage 1: 概念提取
        assert len(extraction.concepts) == 4
        assert isinstance(extraction, ConceptExtractionResult)

        # Stage 2: 检索
        assert len(result.matches) == 4
        assert result.unmatched_concepts == []

        # Stage 3: 断言
        assert len(assertions) >= 1, f"应有至少 1 条断言，实际 {len(assertions)} 条"

        # Stage 4: 伪代码
        assert isinstance(pseudocode, PseudoCode)
        assert len(pseudocode.steps) == 3

        # Stage 5: SQL
        assert "SELECT" in sql
        assert "FROM" in sql

    def test_sql_is_valid_select(self):
        """生成的 SQL 是有效的 SELECT 语句"""
        _, _, _, _, sql = run_full_pipeline("test")
        assert sql.strip().upper().startswith("SELECT")
        assert "FROM" in sql.upper()


class TestAssertionPipelineIntegration:
    """断言集成 — 验证断言确实影响了 SQL"""

    def test_code_assertion_in_sql(self):
        """'活跃客户' 断言 → SQL WHERE 包含 cust_status='01'"""
        req = "统计活跃客户的交易金额"

        # 聚焦到活跃客户概念
        custom_concepts = {
            "concepts": [
                {
                    "concept": "活跃客户", "context": "统计活跃客户",
                    "type": "entity", "candidates": ["活跃用户"],
                    "qualifier": "cust_status = '01'",
                },
                {
                    "concept": "交易金额", "context": "交易金额",
                    "type": "metric", "candidates": ["金额"],
                    "qualifier": "",
                },
            ]
        }

        custom_retrieval = RetrievalResult(
            matches=[
                TableMatch(
                    concept="活跃客户", matched=True, layer=DataLayer.DM,
                    table_name="dm_customer_active", score=0.95,
                    columns=[
                        ColumnMatch(name="cust_id", comment="客户编号", data_type="varchar(32)"),
                        ColumnMatch(
                            name="cust_status", comment="客户状态", data_type="varchar(2)",
                            code_values=[
                                CodeMapping(value="01", meaning="活跃"),
                                CodeMapping(value="02", meaning="休眠"),
                            ],
                        ),
                    ],
                ),
                TableMatch(
                    concept="交易金额", matched=True, layer=DataLayer.DM,
                    table_name="dm_transaction_daily", score=0.92,
                    columns=[
                        ColumnMatch(name="txn_amt", comment="交易金额", data_type="decimal(18,2)"),
                    ],
                ),
            ],
        )

        custom_pseudocode = {
            "title": "统计活跃客户交易金额",
            "steps": [
                {
                    "step_number": 1, "description": "筛选活跃客户",
                    "source_table": "dm_customer_active",
                    "conditions": ["cust_status = '01'"],
                    "joins": [], "aggregations": [],
                    "output": "cust_id",
                },
                {
                    "step_number": 2, "description": "聚合交易",
                    "source_table": "dm_transaction_daily",
                    "conditions": [],
                    "joins": [],
                    "aggregations": ["SUM(txn_amt) AS total_amount"],
                    "output": "total_amount",
                },
            ],
            "todo_items": [],
            "notes": [],
        }

        _, _, assertions, _, sql = run_full_pipeline(req, custom_concepts, custom_pseudocode)

        # 验证断言正确
        code_assertions = [a for a in assertions if a.type.value == "code"]
        assert len(code_assertions) >= 1
        assert code_assertions[0].value == "01"

        # 验证 SQL 包含码值条件
        assert "cust_status" in sql.lower()
        assert "'01'" in sql or "= '01'" in sql


class TestGracefulDegradation:
    """降级路径 — LLM 失败时系统不崩溃"""

    def test_concept_extraction_failure(self):
        """概念提取 LLM 失败 → 空概念 + llm_error"""
        from extractor.concept import extract_concepts

        with mock.patch("extractor.concept.chat_json",
                        side_effect=RuntimeError("LLM timeout")):
            result = extract_concepts("测试需求")

        assert isinstance(result, ConceptExtractionResult)
        assert len(result.concepts) == 0
        assert "LLM timeout" in result.llm_error

    def test_pseudocode_generation_failure(self):
        """伪代码生成失败 → 空 steps PseudoCode"""
        from generator.pseudocode import generate

        with mock.patch("generator.pseudocode.chat_json",
                        side_effect=RuntimeError("LLM timeout")):
            result = generate("test", RetrievalResult())

        assert isinstance(result, PseudoCode)
        assert len(result.steps) == 0
        assert len(result.todo_items) > 0


class TestFullPipelineWithAllComponents:
    """完整集成 — 所有 P1-P4 组件协同工作"""

    def test_assertions_flow_to_sql(self):
        """断言→伪代码→SQL 完整链路"""
        req = "统计活跃客户数"
        custom_concepts = {
            "concepts": [
                {
                    "concept": "活跃客户", "context": "", "type": "entity",
                    "candidates": ["活跃"], "qualifier": "cust_status = '01'",
                },
                {
                    "concept": "客户数", "context": "", "type": "metric",
                    "candidates": ["客户数量"], "qualifier": "",
                },
            ]
        }

        custom_retrieval = RetrievalResult(
            matches=[
                TableMatch(
                    concept="活跃客户", matched=True, layer=DataLayer.DM,
                    table_name="dm_customer", score=0.95,
                    columns=[
                        ColumnMatch(
                            name="cust_status", comment="客户状态", data_type="varchar(2)",
                            code_values=[
                                CodeMapping(value="01", meaning="活跃"),
                                CodeMapping(value="02", meaning="休眠"),
                            ],
                        ),
                        ColumnMatch(name="cust_id", comment="客户编号", data_type="varchar(32)"),
                    ],
                ),
                TableMatch(
                    concept="客户数", matched=True, layer=DataLayer.DM,
                    table_name="dm_customer", score=0.90,
                    columns=[
                        ColumnMatch(name="cust_id", comment="客户编号", data_type="varchar(32)"),
                    ],
                ),
            ],
        )

        # Pseudocode 匹配 "客户数" 概念（COUNT 而非 SUM）
        count_pseudocode = {
            "title": "统计活跃客户数",
            "steps": [
                {
                    "step_number": 1, "description": "筛选活跃客户",
                    "source_table": "dm_customer",
                    "conditions": ["cust_status = '01'"],
                    "joins": [], "aggregations": [], "output": "cust_id",
                },
                {
                    "step_number": 2, "description": "计数",
                    "source_table": "",
                    "conditions": [],
                    "joins": [],
                    "aggregations": ["COUNT(cust_id) AS cust_count"],
                    "output": "cust_count",
                },
            ],
            "todo_items": [],
            "notes": [],
        }

        extraction, result, assertions, pseudocode, sql = run_full_pipeline(
            req, custom_concepts, count_pseudocode, custom_retrieval
        )

        # 断言阶段
        code = [a for a in assertions if a.type.value == "code"]
        agg = [a for a in assertions if a.type.value == "aggregation"]
        assert len(code) >= 1, "活跃客户应产生码值断言"
        assert len(agg) >= 1, "客户数应产生聚合断言"

        # SQL 阶段：断言条件被注入
        assert "cust_status" in sql.lower()
        assert "COUNT" in sql.upper()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
