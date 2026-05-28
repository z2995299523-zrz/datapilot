"""
集成测试 + 边界场景
"""
import pytest
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dictionary.loader import load_dictionary
from dictionary.indexer import build_index
from retrieval.engine import search
from models import (
    BusinessConcept, ConceptType, TableMatch, RetrievalResult,
    DataLayer,
)
from config import CHROMA_COLLECTION


@pytest.fixture(scope="module")
def demo_collection():
    path = Path(__file__).resolve().parent.parent / "demo" / "data_dict.csv"
    data_dict = load_dictionary(path)
    return build_index(data_dict, reset=True)


class TestEndToEndPipeline:
    """全链路：概念 → 分层检索（不调 LLM，用模拟概念覆盖边界）"""

    def test_pipeline_normal_case(self, demo_collection):
        """正常场景：大部分概念在 DM 层命中"""
        concepts = [
            BusinessConcept(concept="客户", type=ConceptType.ENTITY, candidates=["客户信息"]),
            BusinessConcept(concept="渠道", type=ConceptType.DIMENSION, candidates=["渠道类型"]),
            BusinessConcept(concept="产品", type=ConceptType.ENTITY, candidates=["产品信息"]),
            BusinessConcept(concept="交易", type=ConceptType.METRIC, candidates=["交易记录"]),
        ]
        result = search(concepts, demo_collection)
        matched = sum(1 for m in result.matches if m.matched)
        assert matched >= 3  # 至少 3/4 命中
        assert len(result.unmatched_concepts) <= 1

    def test_all_in_dm_layer(self, demo_collection):
        """全部概念都在 DM 层找到"""
        concepts = [
            BusinessConcept(concept="客户汇总", type=ConceptType.ENTITY),
            BusinessConcept(concept="渠道汇总", type=ConceptType.DIMENSION),
            BusinessConcept(concept="产品汇总", type=ConceptType.ENTITY),
            BusinessConcept(concept="交易日报", type=ConceptType.METRIC),
        ]
        result = search(concepts, demo_collection)
        # 全部命中
        matched = sum(1 for m in result.matches if m.matched)
        assert matched == 4
        # 全部在 DM 层
        for m in result.matches:
            assert m.layer == DataLayer.DM
        assert len(result.unmatched_concepts) == 0

    def test_fallback_to_dws(self, demo_collection):
        """DM 没命中，降级到 DWS"""
        concepts = [
            BusinessConcept(concept="风险评级", type=ConceptType.CONDITION, candidates=["风险等级"]),
        ]
        result = search(concepts, demo_collection)
        # 风险评级在 DWS 层
        matched = [m for m in result.matches if m.matched]
        assert len(matched) == 1
        # dws_cust_risk_rating 在 DWS 层
        assert any("risk" in m.table_name.lower() for m in matched)

    def test_fallback_to_ods(self, demo_collection):
        """DM、DWS 都没命中，降级到 ODS"""
        # "证件" 是 ODS 特有的细粒度字段（id_type/id_number），DM/DWS 没有
        concepts = [
            BusinessConcept(concept="证件", type=ConceptType.DIMENSION, candidates=["证件类型", "身份证"]),
        ]
        result = search(concepts, demo_collection)
        matched = [m for m in result.matches if m.matched]
        assert len(matched) >= 1
        # id_type 在 ODS 层 ods_customer_base 表
        ods_match = [m for m in matched if m.layer == DataLayer.ODS]
        assert len(ods_match) >= 1

    def test_cross_layer_matching(self, demo_collection):
        """不同概念命中不同层"""
        concepts = [
            BusinessConcept(concept="客户汇总", type=ConceptType.ENTITY),
            BusinessConcept(concept="风险评级", type=ConceptType.CONDITION, candidates=["风险"]),
            BusinessConcept(concept="交易日志", type=ConceptType.ENTITY, candidates=["日志"]),
        ]
        result = search(concepts, demo_collection)
        layers = {m.layer for m in result.matches if m.matched}
        # 至少 2 个不同的层
        assert len(layers) >= 2


class TestEdgeCases:
    """边界场景"""

    def test_all_unmatched(self, demo_collection):
        """所有概念都未匹配"""
        concepts = [
            BusinessConcept(concept="量子计算机", type=ConceptType.ENTITY),
            BusinessConcept(concept="外星人账户", type=ConceptType.ENTITY),
        ]
        result = search(concepts, demo_collection, threshold=0.99)
        assert len(result.unmatched_concepts) == 2
        assert all(not m.matched for m in result.matches)

    def test_partial_match(self, demo_collection):
        """部分命中，部分未命中"""
        concepts = [
            BusinessConcept(concept="客户", type=ConceptType.ENTITY),
            BusinessConcept(concept="量子计算机", type=ConceptType.ENTITY),
        ]
        result = search(concepts, demo_collection, threshold=0.95)
        matched = sum(1 for m in result.matches if m.matched)
        assert matched == 1
        assert len(result.unmatched_concepts) == 1

    def test_single_concept_multi_candidates(self, demo_collection):
        """一个有多个同义词的概念，找到最佳匹配"""
        concepts = [
            BusinessConcept(
                concept="客户状态",
                type=ConceptType.CONDITION,
                candidates=["状态", "活跃状态", "账户状态"],
            ),
        ]
        result = search(concepts, demo_collection)
        matched = [m for m in result.matches if m.matched]
        assert len(matched) >= 1

    def test_concept_matches_multiple_tables(self, demo_collection):
        """一个概念匹配多张表，取最佳"""
        concepts = [
            BusinessConcept(concept="客户", type=ConceptType.ENTITY, candidates=["客户信息"]),
        ]
        result = search(concepts, demo_collection)
        # 可能匹配 dm_customer_active, ods_customer_base 等
        # 但我们只取最佳匹配（DM 层优先）
        matched = [m for m in result.matches if m.matched]
        assert len(matched) >= 1
        # 最佳匹配应该在 DM 层（优先级最高）
        assert matched[0].layer == DataLayer.DM


class TestRetrievalLogFormat:
    """结构化日志格式"""

    def test_log_has_header(self, demo_collection):
        result = search(
            [BusinessConcept(concept="客户", type=ConceptType.ENTITY)],
            demo_collection,
        )
        log_text = "\n".join(result.retrieval_log)
        assert "DataPilot 分层检索引擎" in log_text
        assert "检索顺序" in log_text

    def test_log_has_summary(self, demo_collection):
        result = search(
            [BusinessConcept(concept="客户", type=ConceptType.ENTITY)],
            demo_collection,
        )
        log_text = "\n".join(result.retrieval_log)
        assert "检索汇总" in log_text
        assert "命中率" in log_text
        assert "总耗时" in log_text

    def test_log_has_layer_stats(self, demo_collection):
        result = search(
            [BusinessConcept(concept="客户", type=ConceptType.ENTITY)],
            demo_collection,
        )
        log_text = "\n".join(result.retrieval_log)
        assert "DM层: 命中" in log_text
        assert "DWS层: 命中" in log_text
        assert "ODS层: 命中" in log_text

    def test_log_shows_match_type(self, demo_collection):
        """日志区分精确匹配和语义匹配"""
        result = search(
            [BusinessConcept(concept="客户", type=ConceptType.ENTITY)],
            demo_collection,
        )
        log_text = "\n".join(result.retrieval_log)
        assert "精确匹配" in log_text or "语义匹配" in log_text


class TestCliIntegration:
    """CLI 集成"""

    def test_help_output(self):
        """CLI --help 正常输出"""
        import subprocess
        result = subprocess.run(
            [sys.executable, "cli.py", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "DataPilot" in result.stdout
        assert "search" in result.stdout
        assert "analyze" in result.stdout

    def test_search_help(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "cli.py", "search", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--req" in result.stdout
        assert "--dict" in result.stdout

    def test_analyze_help(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "cli.py", "analyze", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--req" in result.stdout
        assert "--output" in result.stdout
        assert "json" in result.stdout

    def test_missing_req_exits_error(self):
        """缺少 --req 参数报错"""
        import subprocess
        result = subprocess.run(
            [sys.executable, "cli.py", "search"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_api_key_check_mocked(self):
        """未配置 API Key 时 _check_api_key 调用 sys.exit(1)"""
        from cli import _check_api_key
        with mock.patch("cli.LLM_API_KEY", "your-deepseek-api-key"):
            with mock.patch("sys.exit") as mock_exit:
                _check_api_key()
                mock_exit.assert_called_once_with(1)


class TestMultiConceptAssociation:
    """多概念关联到不同表 — 为伪代码 JOIN 做准备"""

    def test_concepts_share_join_key(self, demo_collection):
        """'客户' 和 '风险评级' 命中不同表，且都有 cust_id 关联键"""
        concepts = [
            BusinessConcept(concept="客户", type=ConceptType.ENTITY),
            BusinessConcept(concept="风险评级", type=ConceptType.CONDITION, candidates=["风险"]),
        ]
        result = search(concepts, demo_collection)
        matched = [m for m in result.matches if m.matched]
        # 至少两张不同的表
        tables = {m.table_name for m in matched}
        assert len(tables) >= 2

        # 两张表都应有 cust_id 字段（跨表关联键）
        all_columns = []
        for m in matched:
            for col in m.columns:
                all_columns.append(col.name)
        assert "cust_id" in all_columns


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
