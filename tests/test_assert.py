"""
测试断言翻译器 — extractor/assert.py
"""
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import (
    BusinessConcept, ConceptType, ConceptExtractionResult,
    RetrievalResult, TableMatch, ColumnMatch, CodeMapping, DataLayer,
    Assertion, AssertionType,
)
from extractor.assertions import (
    build_assertions, _is_code_match, _build_code_assertions,
    _build_time_assertion, _build_aggregation_assertion,
    _infer_agg_function, _build_generic_time_expr, _is_date_column,
    _extract_column_from_qualifier, _is_numeric_column,
)


def _make_concept(name, ctype=ConceptType.ENTITY, qualifier=""):
    return BusinessConcept(concept=name, type=ctype, qualifier=qualifier)


def _make_retrieval(matches):
    return RetrievalResult(matches=matches, unmatched_concepts=[])


def _make_match(concept, table_name, columns, layer=DataLayer.DM, score=0.95):
    return TableMatch(
        concept=concept,
        matched=True,
        layer=layer,
        table_name=table_name,
        table_comment=f"{table_name} comment",
        score=score,
        columns=columns,
    )


def _make_code_col(name, codes, data_type="varchar(10)"):
    return ColumnMatch(
        name=name,
        comment=f"{name} comment",
        data_type=data_type,
        code_values=[CodeMapping(value=v, meaning=m) for v, m in codes],
    )


def _make_plain_col(name, data_type="varchar(50)"):
    return ColumnMatch(name=name, comment=f"{name} comment", data_type=data_type)


class TestCodeMatching:
    """码值匹配逻辑"""

    def test_exact_meaning_match(self):
        """概念名精确包含 meaning"""
        assert _is_code_match("活跃客户", CodeMapping(value="01", meaning="活跃"))
        assert _is_code_match("正常", CodeMapping(value="01", meaning="正常"))

    def test_substring_match(self):
        """子串匹配"""
        assert _is_code_match("高净值客户", CodeMapping(value="03", meaning="高净值"))

    def test_no_match(self):
        """不匹配"""
        assert not _is_code_match("活跃客户", CodeMapping(value="01", meaning="冻结"))
        assert not _is_code_match("测试", CodeMapping(value="01", meaning=""))

    def test_empty_meaning(self):
        """空 meaning 不匹配"""
        assert not _is_code_match("活跃客户", CodeMapping(value="01", meaning=""))


class TestAssertionBuilding:
    """断言构建核心逻辑"""

    def test_code_assertion_active_customer(self):
        """'活跃客户' + {01: 活跃} → CodeAssertion(value='01')"""
        concepts = [_make_concept("活跃客户", ConceptType.ENTITY)]
        retrieval = _make_retrieval([
            _make_match("活跃客户", "dm_customer", [
                _make_code_col("cust_status", [("01", "活跃"), ("02", "休眠")]),
            ]),
        ])
        result = build_assertions(concepts, retrieval)

        assert len(result) == 1
        assert result[0].type == AssertionType.CODE
        assert result[0].column == "cust_status"
        assert result[0].value == "01"
        assert result[0].sql_condition == "cust_status = '01'"
        assert result[0].confidence > 0.8

    def test_condition_concept_code_assertion(self):
        """CONDITION 类型概念也应产生码值断言"""
        concepts = [_make_concept("高风险客户", ConceptType.CONDITION)]
        retrieval = _make_retrieval([
            _make_match("高风险客户", "dm_customer", [
                _make_code_col("risk_level", [("03", "高风险")]),
            ]),
        ])
        result = build_assertions(concepts, retrieval)

        assert len(result) == 1
        assert result[0].type == AssertionType.CODE
        assert result[0].value == "03"

    def test_multiple_code_values_single_match(self):
        """多个码值但只匹配一个"""
        concepts = [_make_concept("休眠客户", ConceptType.ENTITY)]
        retrieval = _make_retrieval([
            _make_match("休眠客户", "dm_customer", [
                _make_code_col("cust_status", [
                    ("01", "活跃"), ("02", "休眠"), ("03", "销户"),
                ]),
            ]),
        ])
        result = build_assertions(concepts, retrieval)

        assert len(result) == 1
        assert result[0].value == "02"

    def test_concept_no_code_match(self):
        """概念无对应码值 → 空断言"""
        concepts = [_make_concept("未知概念", ConceptType.ENTITY)]
        retrieval = _make_retrieval([
            _make_match("未知概念", "some_table", [
                _make_code_col("status", [("01", "有效")]),
            ]),
        ])
        result = build_assertions(concepts, retrieval)
        assert len(result) == 0

    def test_empty_concepts(self):
        """空概念列表 → 空断言列表"""
        result = build_assertions([], _make_retrieval([]))
        assert result == []

    def test_empty_retrieval(self):
        """空检索结果 → 空断言列表"""
        concepts = [_make_concept("活跃客户", ConceptType.ENTITY)]
        result = build_assertions(concepts, _make_retrieval([]))
        assert result == []


class TestTimeAssertion:
    """时间断言"""

    def test_time_assertion_from_qualifier(self):
        """'近6个月' + qualifier → TimeAssertion"""
        concepts = [_make_concept("近6个月", ConceptType.TIME_RANGE,
                                  qualifier="trans_date >= DATE_SUB(NOW(), INTERVAL 6 MONTH)")]
        retrieval = _make_retrieval([
            _make_match("近6个月", "dm_transaction", [
                _make_plain_col("trans_date", "date"),
            ]),
        ])
        result = build_assertions(concepts, retrieval)

        time_assertions = [a for a in result if a.type == AssertionType.TIME]
        assert len(time_assertions) == 1
        assert "DATE_SUB" in time_assertions[0].sql_condition

    def test_generic_time_expr_inference(self):
        """'近6个月' → DATE_SUB(NOW(), INTERVAL 6 MONTH)"""
        expr = _build_generic_time_expr("近6个月")
        assert "INTERVAL 6 MONTH" in expr

        expr = _build_generic_time_expr("最近30天")
        assert "INTERVAL 30 DAY" in expr

    def test_date_column_detection(self):
        """日期列识别"""
        assert _is_date_column("trans_date", "date")
        assert _is_date_column("create_time", "timestamp")
        assert _is_date_column("trade_dt", "varchar")
        assert not _is_date_column("cust_name", "varchar")


class TestAggregationAssertion:
    """聚合断言"""

    def test_aggregation_from_concept_name(self):
        """'交易金额' → SUM"""
        concepts = [_make_concept("交易金额", ConceptType.METRIC)]
        retrieval = _make_retrieval([
            _make_match("交易金额", "dm_transaction", [
                _make_plain_col("txn_amt", "decimal(18,2)"),
            ]),
        ])
        result = build_assertions(concepts, retrieval)

        agg_assertions = [a for a in result if a.type == AssertionType.AGG]
        assert len(agg_assertions) == 1
        assert "SUM(txn_amt)" in agg_assertions[0].sql_condition

    def test_count_for_customer_count(self):
        """'客户数' → COUNT"""
        concepts = [_make_concept("客户数", ConceptType.METRIC)]
        retrieval = _make_retrieval([
            _make_match("客户数", "dm_customer", [
                _make_plain_col("cust_id", "varchar(32)"),
            ]),
        ])
        result = build_assertions(concepts, retrieval)

        agg_assertions = [a for a in result if a.type == AssertionType.AGG]
        assert len(agg_assertions) == 1
        assert "COUNT(cust_id)" in agg_assertions[0].sql_condition

    def test_agg_function_inference(self):
        """聚合函数推断"""
        assert _infer_agg_function("交易金额") == "SUM"
        assert _infer_agg_function("客户数") == "COUNT"
        assert _infer_agg_function("平均交易金额") == "AVG"
        assert _infer_agg_function("最高分") == "MAX"


class TestExtractColumnFromQualifier:
    """_extract_column_from_qualifier — P0 补测"""

    def test_empty_qualifier(self):
        """空 qualifier → 返回空字符串"""
        assert _extract_column_from_qualifier("") == ""
        assert _extract_column_from_qualifier("   ") == ""

    def test_with_space_before_operator(self):
        """带空格的标准 SQL 表达式 → 提取列名"""
        assert _extract_column_from_qualifier("cust_status = '01'") == "cust_status"
        assert _extract_column_from_qualifier("trans_date >= DATE_SUB(NOW(), INTERVAL 6 MONTH)") == "trans_date"

    def test_without_space_before_equal(self):
        """无空格 '=' (如 LLM 生成的 qualifier) → 提取列名"""
        assert _extract_column_from_qualifier("cust_status='01'") == "cust_status"

    def test_no_operator_match(self):
        """无匹配操作符 → 返回空字符串"""
        assert _extract_column_from_qualifier("some_column_name") == ""

    def test_in_operator(self):
        """IN 操作符 → 提取列名"""
        assert _extract_column_from_qualifier("status IN ('01','02')") == "status"


class TestIsNumericColumn:
    """_is_numeric_column — P0 补测"""

    def test_standard_numeric_types(self):
        assert _is_numeric_column("int") is True
        assert _is_numeric_column("decimal(18,2)") is True
        assert _is_numeric_column("float") is True
        assert _is_numeric_column("bigint") is True

    def test_non_numeric_types(self):
        assert _is_numeric_column("varchar(50)") is False
        assert _is_numeric_column("date") is False
        assert _is_numeric_column("text") is False

    def test_empty_type(self):
        assert _is_numeric_column("") is False


class TestCodeAssertionQualifierPath:
    """_build_code_assertions qualifier 匹配路径 — P1 补测"""

    def test_qualifier_based_code_match(self):
        """用 qualifier 中的 meaning 匹配码值（confidence=0.85）

        概念名本身不包含码值 meaning，但 qualifier 中包含 → 走 qualifier 路径。
        """
        concept = BusinessConcept(
            concept="特定客户群", type=ConceptType.CONDITION,
            qualifier="risk_level 包含高风险",
        )
        retrieval = _make_retrieval([
            _make_match("特定客户群", "dm_customer", [
                _make_code_col("risk_level", [("03", "高风险"), ("01", "低风险")]),
            ]),
        ])
        result = build_assertions([concept], retrieval)
        code = [a for a in result if a.type == AssertionType.CODE]
        assert len(code) >= 1  # qualifier 中的 "高风险" 匹配码值 meaning
        assert code[0].confidence == 0.85

    def test_qualifier_no_match_fallback(self):
        """qualifier 中无匹配的 meaning → 不产生断言"""
        concept = BusinessConcept(
            concept="未知客户", type=ConceptType.ENTITY,
            qualifier="some_field 包含 nonexistent",
        )
        retrieval = _make_retrieval([
            _make_match("未知客户", "dm_customer", [
                _make_code_col("status", [("01", "有效")]),
            ]),
        ])
        result = build_assertions([concept], retrieval)
        code = [a for a in result if a.type == AssertionType.CODE]
        assert len(code) == 0  # qualifier 不匹配任何 meaning → 空


class TestBuildTimeAssertionExtra:
    """_build_time_assertion 通用表达式 + None 返回 — P1 补测"""

    def test_generic_expr_from_date_column(self):
        """无 qualifier 但有日期列 → 生成通用时间表达式 (confidence=0.60)"""
        concept = BusinessConcept(
            concept="近6个月", type=ConceptType.TIME_RANGE, qualifier="",
        )
        retrieval = _make_retrieval([
            _make_match("近6个月", "dm_transaction", [
                _make_plain_col("trans_date", "date"),
            ]),
        ])
        result = build_assertions([concept], retrieval)
        time_assertions = [a for a in result if a.type == AssertionType.TIME]
        assert len(time_assertions) == 1
        assert time_assertions[0].confidence == 0.60
        assert "INTERVAL 6 MONTH" in time_assertions[0].sql_condition

    def test_no_qualifier_no_date_column(self):
        """无 qualifier 且无日期列 → 返回 None（不产生断言）"""
        concept = BusinessConcept(
            concept="某个时间段", type=ConceptType.TIME_RANGE, qualifier="",
        )
        retrieval = _make_retrieval([
            _make_match("某个时间段", "dm_customer", [
                _make_plain_col("cust_name", "varchar"),
            ]),
        ])
        result = build_assertions([concept], retrieval)
        time_assertions = [a for a in result if a.type == AssertionType.TIME]
        assert len(time_assertions) == 0


class TestInferAggFunctionFallback:
    """_infer_agg_function fallback 路径 — P1 补测"""

    def test_fallback_sum_for_financial_terms(self):
        """含'成本'/'收入'/'利润' → fallback SUM"""
        assert _infer_agg_function("销售成本") == "SUM"
        assert _infer_agg_function("营业收入") == "SUM"
        assert _infer_agg_function("毛利润") == "SUM"

    def test_unrecognized_returns_empty(self):
        """无法识别的概念 → 返回空字符串"""
        assert _infer_agg_function("某个东西") == ""


class TestIntegration:
    """集成场景"""

    def test_full_scenario_multiple_assertions(self):
        """多概念 → 多种断言类型"""
        concepts = [
            _make_concept("活跃客户", ConceptType.ENTITY),
            _make_concept("近6个月", ConceptType.TIME_RANGE,
                          qualifier="trans_date >= DATE_SUB(NOW(), INTERVAL 6 MONTH)"),
            _make_concept("交易金额", ConceptType.METRIC),
        ]
        retrieval = _make_retrieval([
            _make_match("活跃客户", "dm_customer", [
                _make_code_col("cust_status", [("01", "活跃"), ("02", "休眠")]),
                _make_plain_col("cust_id", "varchar(32)"),
            ]),
            _make_match("近6个月", "dm_transaction", [
                _make_plain_col("trans_date", "date"),
            ]),
            _make_match("交易金额", "dm_transaction", [
                _make_plain_col("txn_amt", "decimal(18,2)"),
            ]),
        ])

        result = build_assertions(concepts, retrieval)

        code = [a for a in result if a.type == AssertionType.CODE]
        time = [a for a in result if a.type == AssertionType.TIME]
        agg = [a for a in result if a.type == AssertionType.AGG]

        assert len(code) >= 1, "应该有码值断言"
        assert len(time) >= 1, "应该有时间断言"
        assert len(agg) >= 1, "应该有聚合断言"

    def test_assertion_sql_condition_format(self):
        """验证 sql_condition 字段格式"""
        concepts = [_make_concept("活跃客户", ConceptType.ENTITY)]
        retrieval = _make_retrieval([
            _make_match("活跃客户", "dm_customer", [
                _make_code_col("cust_status", [("01", "活跃")]),
            ]),
        ])
        result = build_assertions(concepts, retrieval)

        assert result[0].sql_condition == "cust_status = '01'"
        assert "=" in result[0].sql_condition


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
