"""
测试概念提取器
"""
import pytest
import json
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import BusinessConcept, ConceptType, ConceptExtractionResult
from extractor.concept import extract_concepts


SAMPLE_CONCEPTS_JSON = {
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
            "candidates": ["渠道类型", "渠道来源"],
            "qualifier": "",
        },
        {
            "concept": "近6个月",
            "context": "近6个月有交易记录",
            "type": "time_range",
            "candidates": ["最近半年", "过去6个月"],
            "qualifier": "trans_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)",
        },
        {
            "concept": "交易金额",
            "context": "分析销售情况中的金额",
            "type": "metric",
            "candidates": ["交易额", "金额"],
            "qualifier": "",
        },
        {
            "concept": "高风险客户",
            "context": "信用评分低于500分",
            "type": "condition",
            "candidates": ["风险客户", "高风险"],
            "qualifier": "credit_score < 500",
        },
    ]
}


@pytest.fixture
def mock_llm():
    """Mock chat_json，返回预设 dict（模拟 LLM JSON 响应）"""
    with mock.patch("extractor.concept.chat_json") as mock_fn:
        mock_fn.return_value = SAMPLE_CONCEPTS_JSON
        yield mock_fn


class TestConceptExtraction:
    """概念提取"""

    def test_extract_concepts_basic(self, mock_llm):
        result = extract_concepts("统计各渠道近6个月活跃客户数")
        assert isinstance(result, ConceptExtractionResult)
        assert len(result.concepts) == 5
        assert result.raw_requirement == "统计各渠道近6个月活跃客户数"

    def test_concept_types(self, mock_llm):
        result = extract_concepts("test")
        types = {c.type for c in result.concepts}
        assert ConceptType.ENTITY in types
        assert ConceptType.DIMENSION in types
        assert ConceptType.TIME_RANGE in types
        assert ConceptType.METRIC in types
        assert ConceptType.CONDITION in types

    def test_candidates_preserved(self, mock_llm):
        result = extract_concepts("test")
        entity = next(c for c in result.concepts if c.concept == "活跃客户")
        assert len(entity.candidates) > 0
        assert "有效客户" in entity.candidates or "活跃用户" in entity.candidates

    def test_qualifier_for_time_range(self, mock_llm):
        result = extract_concepts("test")
        time_concept = next(c for c in result.concepts if c.type == ConceptType.TIME_RANGE)
        assert "INTERVAL" in time_concept.qualifier or "DATE_SUB" in time_concept.qualifier

    def test_condition_concept(self, mock_llm):
        result = extract_concepts("test")
        cond = next(c for c in result.concepts if c.concept == "高风险客户")
        assert cond.type == ConceptType.CONDITION
        assert "500" in cond.qualifier

    def test_empty_concepts(self, mock_llm):
        """LLM 返回空概念列表"""
        mock_llm.return_value = {"concepts": []}
        result = extract_concepts("无意义文本")
        assert len(result.concepts) == 0

    def test_invalid_type_rejected_by_pydantic(self, mock_llm):
        """LLM 返回无效 type → Pydantic 校验抛出 ValidationError"""
        mock_llm.return_value = {
            "concepts": [{"concept": "测试", "type": "invalid_type"}]
        }
        with pytest.raises(Exception):
            extract_concepts("test")

    def test_llm_failure_graceful_degradation(self):
        """LLM 调用失败 → 返回空 concepts + llm_error"""
        with mock.patch("extractor.concept.chat_json", side_effect=RuntimeError("LLM 超时")):
            result = extract_concepts("测试需求")
        assert isinstance(result, ConceptExtractionResult)
        assert len(result.concepts) == 0
        assert "LLM 超时" in result.llm_error
        assert result.raw_requirement == "测试需求"

    def test_llm_token_usage_tracked(self, mock_llm):
        """TokenTracker 正确记录 token 使用"""
        result = extract_concepts("测试需求")
        assert isinstance(result.llm_token_usage, dict)
        # 即使 mock 返回空 token_usage，字段也应存在
        assert "total_calls" in result.llm_token_usage


class TestRealRequirementSample:
    """使用实际的示例需求文档（不调用 LLM）"""

    def test_sample_req_exists(self):
        path = Path(__file__).resolve().parent.parent / "demo" / "req_sample.txt"
        assert path.exists()

    def test_sample_req_readable(self):
        path = Path(__file__).resolve().parent.parent / "demo" / "req_sample.txt"
        text = path.read_text(encoding="utf-8")
        assert len(text) > 0
        assert "活跃客户" in text
        assert "渠道" in text
        assert "高风险" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
