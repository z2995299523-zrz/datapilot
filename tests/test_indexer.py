"""
测试 ChromaDB 索引器
"""
import pytest
from pathlib import Path
import shutil

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dictionary.loader import load_dictionary
from dictionary.indexer import (
    build_index, rebuild_from_file, _build_document_text, _build_document_id
)
from config import CHROMA_DIR, CHROMA_COLLECTION
from models import DataLayer


@pytest.fixture
def demo_dict():
    """加载 demo 数据字典"""
    path = Path(__file__).resolve().parent.parent / "demo" / "data_dict.csv"
    return load_dictionary(path)


class TestDocumentBuilding:
    """document 文本构造"""

    def test_includes_layer_and_table(self, demo_dict):
        table = demo_dict.tables[0]
        col = table.columns[0]
        text = _build_document_text(table, col)
        assert table.table_name in text
        assert col.name in text

    def test_includes_code_values(self, demo_dict):
        # 找有码值的字段
        for table in demo_dict.tables:
            for col in table.columns:
                if col.code_values:
                    text = _build_document_text(table, col)
                    for cv in col.code_values:
                        assert cv.value in text or cv.meaning in text
                    return
        pytest.skip("没有找到带码值的字段")

    def test_document_id_unique(self, demo_dict):
        ids = set()
        for table in demo_dict.tables:
            for col in table.columns:
                doc_id = _build_document_id(table, col)
                assert doc_id not in ids, f"重复 ID: {doc_id}"
                ids.add(doc_id)


class TestIndexBuild:
    """索引构建"""

    def test_build_index(self, demo_dict):
        collection = build_index(demo_dict, reset=True)
        assert collection.name == CHROMA_COLLECTION
        assert collection.count() > 0

    def test_metadata_fields(self, demo_dict):
        collection = build_index(demo_dict, reset=True)
        # 取一条验证 metadata
        results = collection.get(limit=1)
        assert len(results["metadatas"]) > 0
        meta = results["metadatas"][0]
        assert "layer" in meta
        assert "table_name" in meta
        assert "column_name" in meta
        assert meta["layer"] in ("DM", "DWS", "ODS")

    def test_layer_filter(self, demo_dict):
        """验证按 layer 过滤检索"""
        collection = build_index(demo_dict, reset=True)

        # 只查 DM 层
        dm_results = collection.get(
            where={"layer": "DM"},
        )
        dm_ids = dm_results["ids"]
        assert len(dm_ids) > 0
        assert all("DM:" in id for id in dm_ids)

    def test_rebuild_from_file(self):
        demo_path = Path(__file__).resolve().parent.parent / "demo" / "data_dict.csv"
        collection = rebuild_from_file(str(demo_path))
        assert collection.count() > 0

    def test_rebuild_replaces_old_data(self, demo_dict):
        collection1 = build_index(demo_dict, reset=True)
        count1 = collection1.count()

        collection2 = build_index(demo_dict, reset=True)
        count2 = collection2.count()

        assert count1 == count2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
