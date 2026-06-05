"""
LLM 辅助分类 prompt 模板

遵循项目模式（参见 extractor/prompts.py）:
  - 规则引擎主路径 + LLM fallback
  - 调用 llm_client.chat_json() 返回结构化 dict
"""


def llm_classify_table(ti, all_tables):
    """LLM fallback: 当规则引擎置信度 < 0.5 时调用

    Args:
        ti: TableInfo 待分类表
        all_tables: list[TableInfo] 全部表

    Returns:
        TableClassification | None (失败时返回 None)
    """
    from models import TableClassification, TableRole, DataLayer
    try:
        from llm_client import chat_json

        columns_desc = "\n".join(
            f"  - {c.name} ({c.data_type})"
            + (f" PK" if c.is_primary_key else "")
            + (f" → {c.referenced_table}" if c.referenced_table else "")
            + (f" [{c.comment}]" if c.comment else "")
            for c in ti.columns
        )
        all_table_names = [t.table_name for t in all_tables if t.table_name != ti.table_name]

        system = """你是一个数据仓库建模专家。判断给定的数据库表属于以下哪种角色:

- **fact**: 事实表 — 包含度量指标(金额/数量)和外键指向维表
- **dimension**: 维表 — 描述性属性，少量行，作为参照表
- **bridge**: 桥接表 — 仅含外键，解决多对多关系
- **aggregate**: 汇总表 — 预聚合的数据(含统计列名: count/sum/avg/汇总)"""

        user = f"""## 待分类表
表名: {ti.table_name}
注释: {ti.table_comment}
字段:
{columns_desc}

## 其他表
{', '.join(all_table_names) if all_table_names else '(无)'}

输出 JSON: {{"role": "fact|dimension|bridge|aggregate", "confidence": 0.85, "reasoning": "原因"}}"""

        result = chat_json(system, user)
        role_str = result.get("role", "unknown")
        role = TableRole(role_str) if role_str in [r.value for r in TableRole] else TableRole.UNKNOWN
        confidence = float(result.get("confidence", 0.5))

        return TableClassification(
            table_name=ti.table_name,
            role=role,
            confidence=min(max(confidence, 0.0), 1.0),
            reasoning=result.get("reasoning", "LLM classification"),
            score_detail={},
        )
    except Exception:
        return None


def llm_suggest_relationships(tables, existing_rels):
    """LLM fallback: 当关系密度过低时建议额外的 FK-PK 关系

    Returns:
        list[TableRelationship]
    """
    from models import TableRelationship
    try:
        from llm_client import chat_json

        tables_desc = "\n".join(
            f"  - {t.table_name}: PKs=[{', '.join(c.name for c in t.columns if c.is_primary_key)}]"
            f" | columns=[{', '.join(c.name for c in t.columns[:8])}]"
            for t in tables
        )
        existing_desc = "\n".join(
            f"  - {r.source_table}.{r.source_column} → {r.target_table}.{r.target_column}"
            for r in existing_rels
        ) if existing_rels else "(无已有关系)"

        system = "你是数据仓库建模专家。根据表名和主键列推断外键关系。"
        user = f"""## 所有表
{tables_desc}

## 已检测到关系
{existing_desc}

请推断缺失的 FK-PK 关系，输出 JSON:
{{"relationships": [{{"source_table": "..", "source_column": "..", "target_table": "..", "target_column": "..", "confidence": 0.7}}]}}"""

        result = chat_json(system, user)
        rels = []
        for r in result.get("relationships", []):
            rels.append(TableRelationship(
                source_table=r["source_table"],
                source_column=r["source_column"],
                target_table=r["target_table"],
                target_column=r["target_column"],
                confidence=float(r.get("confidence", 0.6)),
                detection_method="llm",
            ))
        return rels
    except Exception:
        return []
