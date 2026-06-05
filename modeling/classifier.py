"""
表角色分类器 — 将表分为 fact / dimension / bridge / aggregate

使用 6 信号加权评分系统，取最高分作为分类结果。
置信度 < 0.5 时可选 LLM fallback。
"""

from models import TableInfo, ColumnInfo, TableRole, TableClassification


# ── 命名模式关键词 ──
FACT_NAME_PATTERNS = [
    "fact_", "f_", "transaction", "record", "log", "txn",
    "交易", "流水", "明细", "记录", "实绩",
]
DIM_NAME_PATTERNS = [
    "dim_", "d_", "code", "type", "status", "category",
    "字典", "类型", "代码", "维度", "参数", "配置",
]
BRIDGE_NAME_PATTERNS = [
    "bridge", "map", "mapping", "rel_", "xref",
    "关联", "映射", "桥接", "关系",
]
AGG_NAME_PATTERNS = [
    "summary", "agg", "daily", "monthly", "weekly",
    "汇总", "统计", "日报", "月报", "周报", "合计",
]


def _is_numeric_column(col: ColumnInfo) -> bool:
    """判断是否为数值/度量列"""
    t = col.data_type.lower()
    numeric_types = ("int", "decimal", "numeric", "float", "double", "number", "bigint", "smallint")
    return any(nt in t for nt in numeric_types)


def _looks_like_code_column(col: ColumnInfo) -> bool:
    """启发式判断是否为码值列"""
    name = col.name.lower()
    for kw in ("type", "status", "code", "flag", "class", "state",
               "类型", "状态", "代码", "类别", "标志"):
        if kw in name:
            return True
    return False


def classify_table(ti: TableInfo, all_tables: list[TableInfo],
                   llm_enabled: bool = False) -> TableClassification:
    """对一张表进行角色分类

    Args:
        ti: 待分类的表
        all_tables: 所有表（用于引用分析）
        llm_enabled: 低置信度时是否启用 LLM fallback

    Returns:
        TableClassification 包含 role, confidence, reasoning, score_detail
    """
    scores: dict[TableRole, float] = {
        TableRole.FACT: 0.0,
        TableRole.DIMENSION: 0.0,
        TableRole.BRIDGE: 0.0,
        TableRole.AGGREGATE: 0.0,
    }
    reasons: list[str] = []

    name_lower = ti.table_name.lower()
    pk_cols = [c for c in ti.columns if c.is_primary_key]
    fk_cols = [c for c in ti.columns if (c.is_foreign_key or c.referenced_table)]
    numeric_cols = [c for c in ti.columns if _is_numeric_column(c)]
    code_cols = [c for c in ti.columns if (len(c.code_values) > 0 or _looks_like_code_column(c))]

    # ── Signal 1: Naming patterns ──
    if any(kw in name_lower for kw in FACT_NAME_PATTERNS):
        scores[TableRole.FACT] += 1.0
        reasons.append("name matches fact pattern")
    elif any(kw in name_lower for kw in DIM_NAME_PATTERNS):
        scores[TableRole.DIMENSION] += 1.0
        reasons.append("name matches dimension pattern")
    elif any(kw in name_lower for kw in BRIDGE_NAME_PATTERNS):
        scores[TableRole.BRIDGE] += 1.0
        reasons.append("name matches bridge pattern")
    elif any(kw in name_lower for kw in AGG_NAME_PATTERNS):
        scores[TableRole.AGGREGATE] += 1.0
        reasons.append("name matches aggregate pattern")

    # ── Signal 2: Column structure ──
    # Fact: has numeric measures + foreign keys
    if len(numeric_cols) >= 2 and len(fk_cols) >= 1:
        scores[TableRole.FACT] += 1.5
        reasons.append(f"has {len(numeric_cols)} measures + {len(fk_cols)} FKs")
    if len(pk_cols) >= 2 and len(fk_cols) >= 1:
        scores[TableRole.FACT] += 1.0
        reasons.append("composite PK suggests fact table")

    # Dimension: single PK + code-like columns
    if len(pk_cols) == 1 and len(numeric_cols) <= 1 and len(code_cols) >= 1:
        scores[TableRole.DIMENSION] += 1.5
        reasons.append("single PK + code columns suggests dimension")
    if len(ti.columns) <= 5 and len(code_cols) >= 1:
        scores[TableRole.DIMENSION] += 1.0
        reasons.append("small table with code columns suggests dimension")

    # Bridge: only FK columns, no measures
    non_key_cols = [c for c in ti.columns
                    if not c.is_primary_key and not c.is_foreign_key and not c.referenced_table]
    has_measures = any(_is_numeric_column(c) for c in non_key_cols)
    if len(fk_cols) >= 2 and not has_measures:
        scores[TableRole.BRIDGE] += 2.0
        reasons.append("multiple FKs with no measures suggests bridge")

    # Aggregate: has aggregation-like column names
    agg_keywords = ["count", "sum", "avg", "total", "amount", "qty",
                    "笔数", "金额", "汇总", "合计", "均值", "数量"]
    agg_cols = [c for c in ti.columns
                if any(kw in c.name.lower() for kw in agg_keywords)]
    if len(agg_cols) >= 2 and len(fk_cols) <= 1:
        scores[TableRole.AGGREGATE] += 1.5
        reasons.append("pre-aggregated column names suggest aggregate")

    # ── Signal 3: Reference analysis ──
    referenced_by = [
        t for t in all_tables
        if t.table_name != ti.table_name
        and any(c.referenced_table == ti.table_name for c in t.columns)
    ]
    if len(referenced_by) >= 2:
        scores[TableRole.DIMENSION] += 1.0
        reasons.append(f"referenced by {len(referenced_by)} other tables")

    # ── Signal 4: Code values ──
    cols_with_codes = [c for c in ti.columns if len(c.code_values) > 0]
    if len(cols_with_codes) >= 1:
        scores[TableRole.DIMENSION] += 0.5
        reasons.append("contains code value mappings")

    # ── Signal 5: Column count ──
    if len(ti.columns) >= 15:
        scores[TableRole.FACT] += 0.5
    elif len(ti.columns) <= 5:
        scores[TableRole.DIMENSION] += 0.3
        scores[TableRole.BRIDGE] += 0.3

    # ── Signal 6: Default to UNKNOWN if all zero ──
    total_score = sum(scores.values())
    if total_score == 0:
        return TableClassification(
            table_name=ti.table_name,
            role=TableRole.UNKNOWN,
            confidence=0.0,
            reasoning="no signals matched; unable to classify",
            score_detail={k.value: v for k, v in scores.items()},
        )

    # ── Pick winner ──
    sorted_roles = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_role, best_score = sorted_roles[0]
    second_score = sorted_roles[1][1] if len(sorted_roles) > 1 else 0.0

    # Confidence = best / (second + margin)
    confidence = min(best_score / max(second_score + 0.15, 0.15), 1.0)

    # LLM fallback for low confidence
    if confidence < 0.5 and llm_enabled:
        from modeling.prompts import llm_classify_table
        try:
            llm_result = llm_classify_table(ti, all_tables)
            if llm_result and llm_result.role != TableRole.UNKNOWN:
                return llm_result
        except Exception:
            pass  # graceful degradation

    return TableClassification(
        table_name=ti.table_name,
        role=best_role,
        confidence=round(confidence, 3),
        reasoning="; ".join(reasons),
        score_detail={k.value: v for k, v in scores.items()},
    )


def classify_all(tables: list[TableInfo], llm_enabled: bool = False
                 ) -> dict[str, TableClassification]:
    """批量分类所有表"""
    return {t.table_name: classify_table(t, tables, llm_enabled) for t in tables}
