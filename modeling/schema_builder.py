"""
模式构建器 — 将分类 + 关系 + 码值组装为 SchemaDefinition
"""

from models import (TableInfo, TableClassification, TableRelationship, TableRole,
                    SchemaType, SchemaDefinition)


def build_schemas(
    tables: list[TableInfo],
    classifications: dict[str, TableClassification],
    relationships: list[TableRelationship],
    schema_type: SchemaType,
) -> list[SchemaDefinition]:
    """基于分类和关系构建 schema 定义

    当有多个事实表时，每个事实表及其关联的维表形成一个子 schema。
    """
    table_map = {t.table_name: t for t in tables}
    fact_tables = [
        t for t in tables
        if classifications.get(t.table_name, TableClassification(
            table_name=t.table_name)).role == TableRole.FACT
    ]

    if not fact_tables:
        # No fact table: put everything in one schema
        return [SchemaDefinition(
            name="main",
            schema_type=schema_type,
            tables=[t.table_name for t in tables],
            relationships=relationships,
            description="Single schema (no fact table detected)",
        )]

    schemas: list[SchemaDefinition] = []

    for fact in fact_tables:
        # Find all dims directly or indirectly related to this fact
        related_tables = {fact.table_name}
        related_rels: list[TableRelationship] = []
        # BFS from fact
        changed = True
        while changed:
            changed = False
            for rel in relationships:
                if rel.source_table in related_tables and rel.target_table not in related_tables:
                    related_tables.add(rel.target_table)
                    if rel not in related_rels:
                        related_rels.append(rel)
                    changed = True
                if rel.target_table in related_tables and rel.source_table not in related_tables:
                    related_tables.add(rel.source_table)
                    if rel not in related_rels:
                        related_rels.append(rel)
                    changed = True

        schemas.append(SchemaDefinition(
            name=f"schema_{fact.table_name}",
            schema_type=schema_type,
            tables=sorted(related_tables),
            relationships=related_rels,
            description=f"Schema centered on fact table '{fact.table_name}'",
        ))

    # Add unconnected tables as a separate schema if any
    all_connected = set()
    for s in schemas:
        all_connected.update(s.tables)
    orphans = [t.table_name for t in tables if t.table_name not in all_connected]
    if orphans:
        orphan_rels = [r for r in relationships
                       if r.source_table in orphans or r.target_table in orphans]
        schemas.append(SchemaDefinition(
            name="unconnected",
            schema_type=SchemaType.UNKNOWN,
            tables=sorted(orphans),
            relationships=orphan_rels,
            description="Unconnected tables (no relationship to any fact table)",
        ))

    return schemas
