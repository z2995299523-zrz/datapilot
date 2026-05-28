"""
单层匹配器 — 在指定数据层中搜索业务概念对应的表和字段
"""
import re
import chromadb
from config import RETRIEVAL_TOP_K, RETRIEVAL_THRESHOLD
from models import (
    BusinessConcept, TableMatch, ColumnMatch, CodeMapping, DataLayer,
)
from embedding import get_embedding_model


def _build_search_text(concept: BusinessConcept) -> str:
    """构造检索文本：概念 + 同义词"""
    parts = [concept.concept] + concept.candidates
    return " ".join(parts)


def _contains_keyword(text: str, keywords: list[str]) -> bool:
    """检查文本是否包含任一关键词（大小写不敏感）"""
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            return True
    return False


def _parse_code_values(raw: str) -> list[CodeMapping]:
    """从序列化的码值字符串还原 CodeMapping 列表"""
    if not raw:
        return []
    mappings = []
    for pair in raw.split(", "):
        if "=" in pair:
            value, meaning = pair.split("=", 1)
            mappings.append(CodeMapping(value=value.strip(), meaning=meaning.strip()))
    return mappings


def _get_table_columns(
    collection: chromadb.Collection,
    layer: str,
    table_name: str,
) -> list[ColumnMatch]:
    """获取某个表在指定层的所有字段"""
    results = collection.get(
        where={"$and": [
            {"layer": layer},
            {"table_name": table_name},
        ]}
    )
    columns = []
    if results["metadatas"]:
        for meta in results["metadatas"]:
            columns.append(ColumnMatch(
                name=meta["column_name"],
                comment=meta.get("column_comment", ""),
                data_type=meta.get("column_type", ""),
                code_values=_parse_code_values(meta.get("code_values", "")),
            ))
    return columns


def match_layer(
    concept: BusinessConcept,
    collection: chromadb.Collection,
    layer: str,
    top_k: int = RETRIEVAL_TOP_K,
    threshold: float = RETRIEVAL_THRESHOLD,
) -> list[TableMatch]:
    """在指定数据层中搜索概念匹配

    Args:
        concept: 业务概念
        collection: ChromaDB Collection
        layer: 数据层（DM/DWS/ODS）
        top_k: 语义检索返回数量
        threshold: 相似度阈值

    Returns:
        匹配到的 TableMatch 列表（按分数降序）
    """
    keywords = [concept.concept] + concept.candidates
    matched_tables: dict[str, TableMatch] = {}

    # Step 1: 精确匹配 — 获取该层所有文档，检查关键词命中
    all_docs = collection.get(where={"layer": layer})
    if all_docs["metadatas"]:
        for i, meta in enumerate(all_docs["metadatas"]):
            # 搜索范围：表名、字段名、字段注释、表注释、码值
            search_fields = " ".join([
                meta.get("table_name", ""),
                meta.get("table_comment", ""),
                meta.get("column_name", ""),
                meta.get("column_comment", ""),
                meta.get("code_values", ""),
            ])
            if _contains_keyword(search_fields, keywords):
                table_name = meta["table_name"]
                if table_name not in matched_tables:
                    matched_tables[table_name] = TableMatch(
                        concept=concept.concept,
                        matched=True,
                        layer=DataLayer(layer),
                        table_name=table_name,
                        table_comment=meta.get("table_comment", ""),
                        score=1.0,  # 精确匹配满分
                        message=f"精确匹配: {concept.concept} → {table_name}",
                    )

    # Step 2: 语义匹配 — ChromaDB 向量检索
    search_text = _build_search_text(concept)
    model = get_embedding_model()
    query_embedding = model.encode([search_text], show_progress_bar=False)

    semantic_results = collection.query(
        query_embeddings=query_embedding.tolist(),
        where={"layer": layer},
        n_results=top_k,
    )

    if semantic_results["metadatas"] and semantic_results["metadatas"][0]:
        for i, meta in enumerate(semantic_results["metadatas"][0]):
            distance = semantic_results["distances"][0][i] if "distances" in semantic_results else 0
            # ChromaDB cosine: 距离越小越相似，转换为 0-1 分数
            score = 1.0 - distance if distance else 0.0

            if score < threshold:
                continue

            table_name = meta["table_name"]
            # 不覆盖已有的精确匹配结果
            if table_name not in matched_tables:
                matched_tables[table_name] = TableMatch(
                    concept=concept.concept,
                    matched=True,
                    layer=DataLayer(layer),
                    table_name=table_name,
                    table_comment=meta.get("table_comment", ""),
                    score=round(score, 4),
                    message=f"语义匹配: {concept.concept} → {table_name} (score={score:.2f})",
                )

    # Step 3: 对每个匹配到的表，获取所有字段
    result = []
    for table_name, match in matched_tables.items():
        match.columns = _get_table_columns(collection, layer, table_name)
        result.append(match)

    # 按分数降序
    result.sort(key=lambda m: m.score, reverse=True)
    return result
