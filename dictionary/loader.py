"""
数据字典加载器

支持 Excel (.xlsx) 和 CSV 格式
将人工标注的数据字典解析为 Pydantic 结构化数据
"""
import pandas as pd
from pathlib import Path
from typing import Union

from models import (
    DataDictionary, TableInfo, ColumnInfo, CodeMapping, DataLayer
)


# ============================================================================
# 列名推断：支持中英文列名自动映射
# ============================================================================
COLUMN_MAP = {
    # 分层
    "layer": ["layer", "分层", "数据层", "数据分层"],
    # 表
    "table_name": ["table_name", "表名", "tableName"],
    "table_comment": ["table_comment", "表注释", "tableComment"],
    # 字段
    "column_name": ["column_name", "字段名", "columnName"],
    "column_type": ["column_type", "字段类型", "columnType", "数据类型", "类型"],
    "column_comment": ["column_comment", "字段注释", "columnComment", "注释", "说明"],
    # 码值
    "code_values": ["code_values", "码值", "码值映射", "codeValues"],
    # 表关系
    "relations": ["relations", "表关系", "关联表", "relations"],
    # 主键/外键
    "is_primary_key": ["is_primary_key", "主键", "isPrimaryKey"],
    # 源系统（数据血缘）
    "source_system": ["source_system", "源系统", "数据来源系统", "sourceSystem"],
}


def _infer_column(columns: list[str], key: str) -> str | None:
    """推断列名：查找 columns 中与 key 匹配的列"""
    candidates = COLUMN_MAP.get(key, [key])
    for col in columns:
        if col.lower().strip() in candidates or col.strip() in candidates:
            return col
    return None


def _parse_code_values(raw: str) -> list[CodeMapping]:
    """解析码值字符串

    支持格式：
        "01=活跃, 02=休眠, 03=销户"
        "01:活跃;02:休眠;03:销户"
        "1-男, 2-女"
    """
    if pd.isna(raw) or not str(raw).strip():
        return []

    text = str(raw).strip()
    mappings: list[CodeMapping] = []

    # 尝试不同分隔符（优先 ; 因其不受 CSV 逗号冲突影响）
    pairs = []
    if ";" in text:
        pairs = [p.strip() for p in text.split(";") if p.strip()]
    elif "," in text:
        pairs = [p.strip() for p in text.split(",") if p.strip()]

    for pair in pairs:
        for sep in ["=", ":", "-"]:
            if sep in pair:
                parts = pair.split(sep, 1)
                if len(parts) == 2:
                    mappings.append(CodeMapping(
                        value=parts[0].strip(),
                        meaning=parts[1].strip()
                    ))
                    break

    return mappings


def load_dictionary(file_path: Union[str, Path]) -> DataDictionary:
    """加载数据字典文件

    支持的列（自动映射中英文）：
        layer       | 分层       — DM / DWS / ODS
        table_name  | 表名       — 表名
        table_comment | 表注释   — 表注释
        column_name | 字段名     — 字段名
        column_type | 字段类型   — varchar(2) 等
        column_comment | 字段注释 — 字段描述
        code_values | 码值       — "01=活跃, 02=休眠"
        relations   | 表关系     — 关联表信息
        source_system | 源系统   — 数据来源系统（如"核心银行系统"）

    最少必填列：layer, table_name, column_name
    """
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        df = pd.read_csv(file_path, encoding="utf-8-sig")
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {suffix}，支持 .xlsx .xls .csv")

    if df.empty:
        raise ValueError("数据字典为空")

    # 列名推断
    columns = list(df.columns)
    col_layer = _infer_column(columns, "layer")
    col_table_name = _infer_column(columns, "table_name")
    col_table_comment = _infer_column(columns, "table_comment")
    col_column_name = _infer_column(columns, "column_name")
    col_column_type = _infer_column(columns, "column_type")
    col_column_comment = _infer_column(columns, "column_comment")
    col_code_values = _infer_column(columns, "code_values")
    col_relations = _infer_column(columns, "relations")
    col_is_pk = _infer_column(columns, "is_primary_key")
    col_source_system = _infer_column(columns, "source_system")

    # 最少必填列校验
    missing = []
    for name, col in [("layer/分层", col_layer), ("table_name/表名", col_table_name), ("column_name/字段名", col_column_name)]:
        if col is None:
            missing.append(name)
    if missing:
        raise ValueError(f"缺少必填列: {', '.join(missing)}。可用列: {columns}")

    # 按表分组
    table_groups: dict[str, list[dict]] = {}
    table_metas: dict[str, dict] = {}  # layer, table_comment

    for _, row in df.iterrows():
        layer_raw = str(row[col_layer]).strip().upper()
        table_name = str(row[col_table_name]).strip()

        if layer_raw not in ("DM", "DWS", "ODS"):
            raise ValueError(f"无效的数据层 '{layer_raw}'，必须是 DM/DWS/ODS")

        key = f"{layer_raw}:{table_name}"

        if key not in table_groups:
            table_groups[key] = []
            table_metas[key] = {
                "layer": DataLayer(layer_raw),
                "table_comment": str(row.get(col_table_comment, "")).strip() if col_table_comment and not pd.isna(row.get(col_table_comment)) else "",
                "source_system": str(row.get(col_source_system, "")).strip() if col_source_system and not pd.isna(row.get(col_source_system)) else "",
            }

        col_name = str(row[col_column_name]).strip() if not pd.isna(row[col_column_name]) else ""
        if not col_name:
            continue

        col_data = {
            "name": col_name,
            "data_type": str(row.get(col_column_type, "")).strip() if col_column_type and not pd.isna(row.get(col_column_type)) else "",
            "comment": str(row.get(col_column_comment, "")).strip() if col_column_comment and not pd.isna(row.get(col_column_comment)) else "",
        }

        if col_code_values and not pd.isna(row.get(col_code_values)):
            col_data["code_values"] = _parse_code_values(row[col_code_values])

        if col_is_pk and not pd.isna(row.get(col_is_pk)):
            val = str(row[col_is_pk]).strip().lower()
            col_data["is_primary_key"] = val in ("true", "1", "yes", "是")

        if col_relations and not pd.isna(row.get(col_relations)):
            col_data["referenced_table"] = str(row[col_relations]).strip()

        table_groups[key].append(col_data)

    # 组装
    tables: list[TableInfo] = []
    for key, cols in table_groups.items():
        meta = table_metas[key]
        tables.append(TableInfo(
            table_name=key.split(":", 1)[1],
            table_comment=meta["table_comment"],
            layer=meta["layer"],
            columns=[ColumnInfo(**c) for c in cols],
            source_file=str(file_path.name),
            source_system=meta.get("source_system", ""),
        ))

    return DataDictionary(
        tables=tables,
        metadata={"source": str(file_path.resolve()), "table_count": len(tables)}
    )
