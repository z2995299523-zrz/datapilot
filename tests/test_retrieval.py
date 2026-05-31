"""
测试检索引擎：matcher / ranker / engine
"""
import pytest
from pathlib import Path
import shutil

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dictionary.loader import load_dictionary
from dictionary.indexer import build_index
from models import (
    BusinessConcept, ConceptType, TableMatch, ColumnMatch,
    DataLayer, RetrievalResult,
)
from retrieval.matcher import (
    match_layer, _build_search_text, _contains_keyword,
    match_layer_hybrid, _exact_match_via_db,
)
from retrieval.ranker import rank_matches, merge_table_matches, _merge_columns
from retrieval.engine import search, search_from_extraction
from config import CHROMA_DIR


@pytest.fixture(scope="module")
def demo_collection():
    """加载 demo 数据字典并构建索引（module 级复用）"""
    path = Path(__file__).resolve().parent.parent / "demo" / "data_dict.csv"
    data_dict = load_dictionary(path)
    collection = build_index(data_dict, reset=True)
    return collection


@pytest.fixture(scope="module")
def demo_dict():
    path = Path(__file__).resolve().parent.parent / "demo" / "data_dict.csv"
    return load_dictionary(path)


class TestMatcherHelpers:
    """匹配器工具函数"""

    def test_build_search_text(self):
        concept = BusinessConcept(
            concept="活跃客户",
            type=ConceptType.ENTITY,
            candidates=["活跃用户", "有效客户"],
        )
        text = _build_search_text(concept)
        assert "活跃客户" in text
        assert "活跃用户" in text
        assert "有效客户" in text

    def test_contains_keyword(self):
        assert _contains_keyword("客户状态字段", ["客户"])
        assert _contains_keyword("channel_type", ["渠道", "channel"])
        assert not _contains_keyword("产品汇总", ["客户"])

    def test_contains_keyword_case_insensitive(self):
        assert _contains_keyword("Channel_Type", ["channel"])


class TestMatcher:
    """单层匹配器"""

    def test_exact_match_by_concept(self, demo_collection):
        """精确匹配：概念词直接命中表名或字段名"""
        matches = match_layer(
            BusinessConcept(concept="客户", type=ConceptType.ENTITY, candidates=["客户信息"]),
            demo_collection,
            layer="DM",
        )
        assert len(matches) > 0
        # dm_customer_active 应在结果中
        table_names = [m.table_name for m in matches]
        assert "dm_customer_active" in table_names

    def test_exact_match_by_candidate(self, demo_collection):
        """通过同义词命中"""
        matches = match_layer(
            BusinessConcept(concept="渠道来源", type=ConceptType.DIMENSION, candidates=["渠道类型", "channel"]),
            demo_collection,
            layer="DM",
        )
        assert len(matches) > 0
        assert any("channel" in m.table_name.lower() for m in matches)

    def test_semantic_match(self, demo_collection):
        """语义匹配：概念和字段之间没有直接字面匹配，但语义相近"""
        matches = match_layer(
            BusinessConcept(concept="用户", type=ConceptType.ENTITY, candidates=["使用者"]),
            demo_collection,
            layer="DM",
        )
        # "用户" 和 "客户" 语义相近，应该能通过 embedding 匹配到
        assert len(matches) > 0

    def test_no_match(self, demo_collection):
        """完全不相关概念不应匹配"""
        matches = match_layer(
            BusinessConcept(concept="量子计算机", type=ConceptType.ENTITY, candidates=["量子计算"]),
            demo_collection,
            layer="DM",
            threshold=0.9,  # 高阈值确保不匹配
        )
        # 应该没有或很少匹配，且分数低于阈值
        high_score = [m for m in matches if m.score >= 0.9]
        assert len(high_score) == 0

    def test_returns_full_table_columns(self, demo_collection):
        """匹配后应返回表的完整字段列表"""
        matches = match_layer(
            BusinessConcept(concept="客户", type=ConceptType.ENTITY, candidates=["客户信息"]),
            demo_collection,
            layer="DM",
        )
        dm_customer = next(
            (m for m in matches if m.table_name == "dm_customer_active"),
            None
        )
        assert dm_customer is not None
        assert len(dm_customer.columns) > 1  # 不只一个字段

    def test_code_values_in_results(self, demo_collection):
        """匹配结果中应包含码值信息"""
        matches = match_layer(
            BusinessConcept(concept="客户状态", type=ConceptType.CONDITION, candidates=["状态"]),
            demo_collection,
            layer="DM",
        )
        # 找有码值的字段
        all_code_values = []
        for m in matches:
            for col in m.columns:
                all_code_values.extend(col.code_values)
        assert len(all_code_values) > 0

    def test_layer_filter_respected(self, demo_collection):
        """确保只搜索指定层的数据"""
        dm_matches = match_layer(
            BusinessConcept(concept="客户", type=ConceptType.ENTITY),
            demo_collection,
            layer="DM",
        )
        # 所有匹配结果都应该是 DM 层
        for m in dm_matches:
            assert m.layer == DataLayer.DM


class TestRanker:
    """排序 + 去重"""

    def test_dedup_keeps_higher_score(self):
        m1 = TableMatch(concept="客户", matched=True, table_name="t1", score=0.8)
        m2 = TableMatch(concept="客户", matched=True, table_name="t1", score=0.95)
        result = rank_matches([m1, m2])
        assert len(result) == 1
        assert result[0].score == 0.95

    def test_different_concepts_same_table_kept(self):
        """不同概念命中同一张表，保留两条"""
        m1 = TableMatch(concept="客户", matched=True, table_name="t1", score=0.8)
        m2 = TableMatch(concept="渠道", matched=True, table_name="t1", score=0.7)
        result = rank_matches([m1, m2])
        assert len(result) == 2

    def test_sort_by_score_desc(self):
        m1 = TableMatch(concept="客户", matched=True, table_name="t1", score=0.5)
        m2 = TableMatch(concept="渠道", matched=True, table_name="t2", score=0.9)
        m3 = TableMatch(concept="产品", matched=True, table_name="t3", score=0.7)
        result = rank_matches([m1, m2, m3])
        assert result[0].score == 0.9
        assert result[1].score == 0.7
        assert result[2].score == 0.5

    def test_empty_list(self):
        assert rank_matches([]) == []

    def test_merge_columns(self):
        cols_a = [ColumnMatch(name="col1", comment="a"), ColumnMatch(name="col2", comment="b")]
        cols_b = [ColumnMatch(name="col2", comment="b2"), ColumnMatch(name="col3", comment="c")]
        merged = _merge_columns(cols_a, cols_b)
        assert len(merged) == 3
        names = [c.name for c in merged]
        assert names == ["col1", "col2", "col3"]


class TestEngine:
    """分层检索引擎"""

    def test_layer_priority_dm_first(self, demo_collection):
        """DM 层命中则不再搜索 DWS/ODS"""
        concepts = [
            BusinessConcept(concept="活跃客户", type=ConceptType.ENTITY, candidates=["有效客户"]),
        ]
        result = search(concepts, demo_collection)
        assert len(result.matches) > 0
        # DM 命中后不应该查 DWS（日志中 DWS 命中一直为 0）
        log_text = "\n".join(result.retrieval_log)
        assert "命中" in log_text
        assert "dm_customer_active" in log_text
        # 汇总中 DWS/ODS 命中应为 0
        assert "DWS层: 命中 0" in log_text
        assert "ODS层: 命中 0" in log_text

    def test_unmatched_concept(self, demo_collection):
        """完全不存在的概念，三层均未命中"""
        concepts = [
            BusinessConcept(concept="量子计算机", type=ConceptType.ENTITY),
        ]
        result = search(concepts, demo_collection, threshold=0.95)
        assert len(result.unmatched_concepts) == 1
        assert "量子计算机" in result.unmatched_concepts

    def test_log_tracks_each_layer(self, demo_collection):
        """检索日志记录每层过程"""
        concepts = [
            BusinessConcept(concept="客户", type=ConceptType.ENTITY, candidates=["客户信息"]),
        ]
        result = search(concepts, demo_collection)
        log_text = "\n".join(result.retrieval_log)
        assert "检索概念" in log_text
        assert "客户" in log_text
        assert "DM层" in log_text

    def test_multi_concept_search(self, demo_collection):
        """多个概念同时检索"""
        concepts = [
            BusinessConcept(concept="客户", type=ConceptType.ENTITY, candidates=["客户信息"]),
            BusinessConcept(concept="渠道", type=ConceptType.DIMENSION, candidates=["渠道类型"]),
            BusinessConcept(concept="产品", type=ConceptType.ENTITY, candidates=["产品信息"]),
        ]
        result = search(concepts, demo_collection)
        assert len(result.matches) > 0
        # 每个概念都应该有匹配结果（或标记为未匹配）
        total = len(result.matches) + len(result.unmatched_concepts)
        assert total == 3


class TestHybridRetrieval:
    """match_layer_hybrid / _exact_match_via_db — P0 补测"""

    @pytest.fixture
    def mock_db_conn(self):
        """创建带 information_schema.columns 的 SQLite 内存库"""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        # SQLite 用 ATTACH 模拟 information_schema 数据库
        conn.execute("ATTACH DATABASE ':memory:' AS information_schema")
        conn.execute("""
            CREATE TABLE information_schema.columns (
                TABLE_NAME TEXT, TABLE_COMMENT TEXT, COLUMN_NAME TEXT,
                COLUMN_COMMENT TEXT, TABLE_SCHEMA TEXT
            )
        """)
        conn.execute("""INSERT INTO information_schema.columns VALUES
            ('dm_customer', '客户表', 'cust_id', '客户ID', 'DM'),
            ('dm_customer', '客户表', 'cust_status', '客户状态', 'DM'),
            ('dm_transaction', '交易表', 'trans_date', '交易日期', 'DM'),
            ('dws_channel', '渠道表', 'channel_type', '渠道类型', 'DWS')
        """)
        conn.commit()
        return conn

    def test_exact_match_via_db_hit(self, mock_db_conn):
        """精确匹配命中 → 返回 TableMatch"""
        concept = BusinessConcept(concept="客户", type=ConceptType.ENTITY)
        result = _exact_match_via_db(concept, mock_db_conn, "DM")
        assert result is not None
        assert result.table_name == "dm_customer"
        assert result.score == 1.0
        assert result.matched is True

    def test_exact_match_via_db_miss(self, mock_db_conn):
        """无匹配 → 返回 None"""
        concept = BusinessConcept(concept="不存在的概念", type=ConceptType.ENTITY)
        result = _exact_match_via_db(concept, mock_db_conn, "DM")
        assert result is None

    def test_exact_match_via_db_wrong_layer(self, mock_db_conn):
        """概念在 DM 但查 ODS → 返回 None"""
        concept = BusinessConcept(concept="客户", type=ConceptType.ENTITY)
        result = _exact_match_via_db(concept, mock_db_conn, "ODS")
        assert result is None

    def test_exact_match_via_db_db_failure(self):
        """数据库异常 → 返回 None (静默降级)"""
        import sqlite3
        bad_conn = sqlite3.connect(":memory:")
        bad_conn.close()  # 关闭后执行会抛异常
        concept = BusinessConcept(concept="客户", type=ConceptType.ENTITY)
        result = _exact_match_via_db(concept, bad_conn, "DM")
        assert result is None

    def test_match_layer_hybrid_with_db(self, mock_db_conn, demo_collection):
        """有 DB 连接 → 优先走 information_schema"""
        concept = BusinessConcept(concept="客户", type=ConceptType.ENTITY,
                                  candidates=["客户信息"])
        results = match_layer_hybrid(concept, demo_collection, "DM", db_conn=mock_db_conn)
        assert len(results) > 0
        assert results[0].score == 1.0
        # 结果来自 information_schema 精确匹配
        assert results[0].table_name is not None

    def test_match_layer_hybrid_without_db(self, demo_collection):
        """无 DB 连接 → fallback 到 ChromaDB"""
        concept = BusinessConcept(concept="客户", type=ConceptType.ENTITY)
        results = match_layer_hybrid(concept, demo_collection, "DM", db_conn=None)
        # 结果取决于 ChromaDB，至少应该返回列表
        assert isinstance(results, list)

    def test_match_layer_hybrid_db_failure_fallback(self, demo_collection):
        """DB 查询异常 → fallback 到 ChromaDB"""
        import sqlite3
        bad_conn = sqlite3.connect(":memory:")
        bad_conn.close()
        concept = BusinessConcept(concept="客户", type=ConceptType.ENTITY)
        results = match_layer_hybrid(concept, demo_collection, "DM", db_conn=bad_conn)
        # 应该静默降级到 ChromaDB，不抛异常
        assert isinstance(results, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
