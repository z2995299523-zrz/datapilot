"""
FK-PK 关系检测器 — 自动发现表之间的外键关系

4 层优先级递减:
  1. 显式声明 (ColumnInfo.referenced_table)
  2. 名称精确匹配 (col name == other table PK name)
  3. 语义匹配 (col name ≈ other PK name, 编辑距离)
  4. 类型匹配 (同名列 + 同类型 + 目标列为 PK)
  5. LLM 兜底 (关系密度过低时触发)
"""

from models import TableInfo, ColumnInfo, TableRelationship, RelationshipType


def _clean_name(name: str) -> str:
    """去掉 _id / _pk 后缀做语义对比"""
    return name.lower().replace("_id", "").replace("_pk", "").replace("_fk", "")


def _semantic_match(a: str, b: str) -> bool:
    """语义名匹配: cust_id ≈ customer_id"""
    ca = _clean_name(a)
    cb = _clean_name(b)
    if ca == cb:
        return True
    if ca in cb or cb in ca:
        return True
    # Simple edit distance ratio
    if len(ca) >= 3 and len(cb) >= 3 and _ratio(ca, cb) > 0.7:
        return True
    return False


def _ratio(a: str, b: str) -> float:
    """简单的字符集重叠率"""
    set_a, set_b = set(a), set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def detect_relationships(tables: list[TableInfo],
                         llm_enabled: bool = False) -> list[TableRelationship]:
    """检测所有表之间的 FK-PK 关系"""
    relationships: list[TableRelationship] = []
    table_map = {t.table_name: t for t in tables}
    seen_pairs: set[tuple[str, str, str, str]] = set()

    def _add_rel(src_tbl, src_col, tgt_tbl, tgt_col, confidence, method):
        key = (src_tbl, src_col, tgt_tbl, tgt_col)
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        relationships.append(TableRelationship(
            source_table=src_tbl,
            source_column=src_col,
            target_table=tgt_tbl,
            target_column=tgt_col,
            confidence=confidence,
            detection_method=method,
        ))

    # ── Priority 1: Explicit FK declarations ──
    for ti in tables:
        for col in ti.columns:
            if col.referenced_table and col.referenced_table in table_map:
                target = table_map[col.referenced_table]
                target_pk = next((c for c in target.columns if c.is_primary_key), None)
                if target_pk:
                    _add_rel(ti.table_name, col.name, col.referenced_table,
                             target_pk.name, 1.0, "explicit_fk")
                else:
                    # Try to infer by column name match
                    match = next((c for c in target.columns
                                  if _semantic_match(col.name, c.name)), None)
                    if match:
                        _add_rel(ti.table_name, col.name, col.referenced_table,
                                 match.name, 0.85, "explicit_fk_inferred_pk")

    # ── Priority 2: Name-based matching (FK column → PK column) ──
    for ti in tables:
        for col in ti.columns:
            if not col.name.lower().endswith("_id") and not col.name.lower().endswith("_key"):
                continue
            for other_name, other in table_map.items():
                if other_name == ti.table_name:
                    continue
                other_pk = next((c for c in other.columns if c.is_primary_key), None)
                if other_pk and other_pk.name.lower() == col.name.lower():
                    _add_rel(ti.table_name, col.name, other_name,
                             other_pk.name, 0.85, "name_match")

    # ── Priority 3: Semantic name matching ──
    for ti in tables:
        for col in ti.columns:
            if len(col.name) < 3:
                continue
            for other_name, other in table_map.items():
                if other_name == ti.table_name:
                    continue
                other_pk = next((c for c in other.columns if c.is_primary_key), None)
                if other_pk and _semantic_match(col.name, other_pk.name):
                    _add_rel(ti.table_name, col.name, other_name,
                             other_pk.name, 0.70, "semantic_match")

    # ── Priority 4: Type-based matching ──
    for ti in tables:
        for col in ti.columns:
            if col.is_primary_key:
                continue
            for other_name, other in table_map.items():
                if other_name == ti.table_name:
                    continue
                for other_col in other.columns:
                    if not other_col.is_primary_key:
                        continue
                    if (col.name.lower() == other_col.name.lower()
                            and col.data_type.lower() == other_col.data_type.lower()):
                        _add_rel(ti.table_name, col.name, other_name,
                                 other_col.name, 0.65, "type_match")

    # ── Priority 5: LLM fallback ──
    density = len(relationships) / max(len(tables), 1)
    if density < 0.3 and llm_enabled:
        try:
            from modeling.prompts import llm_suggest_relationships
            extra = llm_suggest_relationships(tables, relationships)
            for rel in extra:
                _add_rel(rel.source_table, rel.source_column,
                         rel.target_table, rel.target_column,
                         rel.confidence, rel.detection_method)
        except Exception:
            pass

    return relationships
