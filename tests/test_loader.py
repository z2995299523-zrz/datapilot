"""
测试数据字典加载器
"""
import pytest
import tempfile
from pathlib import Path
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dictionary.loader import load_dictionary, _parse_code_values
from models import DataLayer


class TestCodeValueParsing:
    """码值解析"""

    def test_comma_separated(self):
        result = _parse_code_values("01=活跃, 02=休眠, 03=销户")
        assert len(result) == 3
        assert result[0].value == "01"
        assert result[0].meaning == "活跃"
        assert result[2].value == "03"
        assert result[2].meaning == "销户"

    def test_semicolon_separated(self):
        result = _parse_code_values("1:男;2:女")
        assert len(result) == 2
        assert result[0].value == "1"
        assert result[0].meaning == "男"

    def test_dash_separated(self):
        result = _parse_code_values("1-是, 0-否")
        assert len(result) == 2
        assert result[1].value == "0"
        assert result[1].meaning == "否"

    def test_empty(self):
        assert _parse_code_values("") == []
        assert _parse_code_values(None) == []


class TestLoadDictionary:
    """完整加载流程"""

    @pytest.fixture
    def sample_csv(self, tmp_path):
        """构造一个最小可用的数据字典 CSV"""
        content = """layer,table_name,table_comment,column_name,column_type,column_comment,code_values
DM,dm_test,测试表,id,int,主键ID,主键
DM,dm_test,测试表,status,varchar(2),状态,01=正常; 02=异常
DWS,dws_test,服务层测试表,amount,decimal,金额,合计金额
ODS,ods_test,原始表,raw_data,text,原始数据,原始字符串
"""
        path = tmp_path / "test_dict.csv"
        path.write_text(content, encoding="utf-8")
        return path

    def test_load_valid_csv(self, sample_csv):
        result = load_dictionary(sample_csv)
        assert len(result.tables) == 3

        # Layer 信息
        layers = {t.table_name: t.layer for t in result.tables}
        assert layers["dm_test"] == DataLayer.DM
        assert layers["dws_test"] == DataLayer.DWS
        assert layers["ods_test"] == DataLayer.ODS

    def test_load_dm_table_columns(self, sample_csv):
        result = load_dictionary(sample_csv)
        dm_table = next(t for t in result.tables if t.table_name == "dm_test")
        assert len(dm_table.columns) == 2
        assert dm_table.table_comment == "测试表"

    def test_code_values_parsed(self, sample_csv):
        result = load_dictionary(sample_csv)
        dm_table = next(t for t in result.tables if t.table_name == "dm_test")
        col = next(c for c in dm_table.columns if c.name == "status")
        assert len(col.code_values) == 2
        assert col.code_values[0].value == "01"
        assert col.code_values[0].meaning == "正常"

    def test_table_grouping(self, sample_csv):
        """同一个表的多行字段合并到一个 TableInfo"""
        result = load_dictionary(sample_csv)
        assert len(result.tables) == 3  # 3 个不同表

    def test_metadata(self, sample_csv):
        result = load_dictionary(sample_csv)
        assert "source" in result.metadata
        assert result.metadata["table_count"] == 3

    def test_empty_csv(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("layer,table_name,column_name\n", encoding="utf-8")
        with pytest.raises(ValueError, match="空"):
            load_dictionary(path)

    def test_missing_required_columns(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text("name,age\n张三,25\n", encoding="utf-8")
        with pytest.raises(ValueError, match="缺少必填列"):
            load_dictionary(path)

    def test_invalid_layer(self, tmp_path):
        path = tmp_path / "invalid.csv"
        path.write_text("layer,table_name,column_name\nCDM,test,col1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="无效的数据层"):
            load_dictionary(path)


class TestLoadDemoDictionary:
    """加载 demo 数据字典"""

    def test_load_demo(self):
        path = Path(__file__).resolve().parent.parent / "demo" / "data_dict.csv"
        result = load_dictionary(path)
        assert len(result.tables) > 0

        # 三层都应该有
        layers = {t.layer for t in result.tables}
        assert DataLayer.DM in layers
        assert DataLayer.DWS in layers
        assert DataLayer.ODS in layers

    def test_demo_column_count(self):
        path = Path(__file__).resolve().parent.parent / "demo" / "data_dict.csv"
        result = load_dictionary(path)
        total_cols = sum(len(t.columns) for t in result.tables)
        assert total_cols > 20  # 足够多的字段用于测试检索


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
