"""
ChromaDB 索引器

将结构化 DataDictionary 写入向量数据库
每条 document = 一个字段（table + column + comment + code_values 拼接为文本）
metadata 包含 layer, table_name, column_name 用于过滤检索
"""
import chromadb
from chromadb.config import Settings as ChromaSettings
from tqdm import tqdm
from embedding import get_embedding_model

from config import (
    CHROMA_DIR, CHROMA_COLLECTION,
    EMBEDDING_MODEL, EMBEDDING_DEVICE
)
from models import DataDictionary, TableInfo, ColumnInfo
from dictionary.loader import load_dictionary


# ============================================================================
# 向量化文本构造
# ============================================================================

def _build_document_text(table: TableInfo, column: ColumnInfo) -> str:
    """构造一条 document 的文本，用于 embedding

    包含：表注释 + 表名 + 字段名 + 字段注释 + 数据类型 + 码值含义 + 字段类型
    """
    parts = []

    if column.is_primary_key:
        parts.append("[主键]")

    parts.append(f"表: {table.table_name}")
    if table.table_comment:
        parts.append(f"表描述: {table.table_comment}")
    parts.append(f"字段: {column.name}")
    if column.comment:
        parts.append(f"字段描述: {column.comment}")
    if column.data_type:
        parts.append(f"类型: {column.data_type}")

    if column.code_values:
        codes = ", ".join(f"{cv.value}={cv.meaning}" for cv in column.code_values)
        parts.append(f"码值: {codes}")

    if column.referenced_table:
        parts.append(f"关联表: {column.referenced_table}")

    return ", ".join(parts)


def _build_document_id(table: TableInfo, column: ColumnInfo) -> str:
    """唯一 ID"""
    return f"{table.layer.value}:{table.table_name}:{column.name}"


# ============================================================================
# 索引构建
# ============================================================================

def build_index(
    data_dict: DataDictionary,
    embedding_model: str = EMBEDDING_MODEL,
    device: str = EMBEDDING_DEVICE,
    reset: bool = False,
) -> chromadb.Collection:
    """将 DataDictionary 写入 ChromaDB

    Args:
        data_dict: 结构化数据字典
        embedding_model: HuggingFace 模型名
        device: 推理设备
        reset: True 时删除已有 Collection 重建

    Returns:
        ChromaDB Collection 对象
    """
    model = get_embedding_model()

    # 连接 ChromaDB（持久化模式）
    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=ChromaSettings(anonymized_telemetry=False),
    )

    # 重置
    if reset:
        try:
            client.delete_collection(CHROMA_COLLECTION)
        except Exception:
            pass

    # 获取或创建
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"description": "DataPilot 数据字典", "hnsw:space": "cosine"},
    )

    # 构造 documents
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for table in data_dict.tables:
        for col in table.columns:
            ids.append(_build_document_id(table, col))
            documents.append(_build_document_text(table, col))
            metadatas.append({
                "layer": table.layer.value,
                "table_name": table.table_name,
                "table_comment": table.table_comment,
                "column_name": col.name,
                "column_comment": col.comment,
                "column_type": col.data_type,
                "is_primary_key": str(col.is_primary_key),
                "code_values": _serialize_code_values(col.code_values),
                "referenced_table": col.referenced_table or "",
            })

    # 批量生成 embedding
    embeddings = model.encode(documents, show_progress_bar=True)

    # 写入
    collection.add(
        ids=ids,
        documents=documents,
        embeddings=[e.tolist() for e in embeddings],
        metadatas=metadatas,
    )

    return collection


def _serialize_code_values(code_values: list) -> str:
    """序列化码值，存到 metadata"""
    if not code_values:
        return ""
    return ", ".join(f"{cv.value}={cv.meaning}" for cv in code_values)


# ============================================================================
# 重建索引快捷函数
# ============================================================================

def rebuild_from_file(file_path: str) -> chromadb.Collection:
    """从字典文件（Excel/CSV）重建向量库"""
    data_dict = load_dictionary(file_path)
    return build_index(data_dict, reset=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        print(f"正在从 {path} 构建向量库...")
        collection = rebuild_from_file(path)
        print(f"✓ 完成，共 {collection.count()} 条记录")
    else:
        print("用法: python -m dictionary.indexer <字典文件路径>")
