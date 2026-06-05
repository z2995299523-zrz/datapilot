"""
模式分类器 — 判断数仓模式是星型 / 雪花型 / 3NF

算法: BFS 计算从维表到事实表的平均最短路径深度
  avg_depth ≤ 2.0   → STAR (所有维直连事实表)
  2.0 < avg ≤ 3.5   → SNOWFLAKE (维表有子维)
  avg > 3.5         → 3NF (深度规范化)
"""

from collections import defaultdict, deque

from models import (TableInfo, TableRelationship, TableClassification,
                    TableRole, SchemaType, SchemaDefinition)


def classify_schema(
    tables: list[TableInfo],
    relationships: list[TableRelationship],
    classifications: dict[str, TableClassification],
    name: str = "default",
) -> SchemaDefinition:
    """对一组表及其关系进行分类

    Returns:
        SchemaDefinition with schema_type, name, tables, relationships
    """
    table_names = [t.table_name for t in tables]

    if len(tables) < 2:
        return SchemaDefinition(
            name=name,
            schema_type=SchemaType.UNKNOWN,
            tables=table_names,
            relationships=relationships,
            description="Too few tables to classify",
        )

    # ── Build adjacency graph ──
    graph: dict[str, set[str]] = defaultdict(set)
    for rel in relationships:
        graph[rel.source_table].add(rel.target_table)
        graph[rel.target_table].add(rel.source_table)

    fact_tables = {
        t.table_name for t in tables
        if classifications.get(t.table_name, TableClassification(
            table_name=t.table_name)).role == TableRole.FACT
    }
    dim_tables = {
        t.table_name for t in tables
        if classifications.get(t.table_name, TableClassification(
            table_name=t.table_name)).role == TableRole.DIMENSION
    }

    if not dim_tables:
        return SchemaDefinition(
            name=name,
            schema_type=SchemaType.THREEF_NF,
            tables=table_names,
            relationships=relationships,
            description="No dimensions detected — likely 3NF",
        )

    # ── BFS from each dimension to nearest fact table ──
    dim_depths: list[int] = []
    for dim in dim_tables:
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(dim, 0)])
        found_depth: int | None = None
        while queue:
            node, depth = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            if node in fact_tables:
                found_depth = depth
                break
            for neighbor in graph.get(node, set()):
                if neighbor not in visited:
                    queue.append((neighbor, depth + 1))
        if found_depth is not None:
            dim_depths.append(found_depth)

    if not dim_depths:
        return SchemaDefinition(
            name=name,
            schema_type=SchemaType.THREEF_NF,
            tables=table_names,
            relationships=relationships,
            description="No dimensions connected to facts",
        )

    avg_depth = sum(dim_depths) / len(dim_depths)

    if avg_depth <= 2.0:
        schema_type = SchemaType.STAR
        desc = f"Star schema: avg dim-to-fact depth = {avg_depth:.1f}"
    elif avg_depth <= 3.5:
        schema_type = SchemaType.SNOWFLAKE
        desc = f"Snowflake schema: avg dim depth = {avg_depth:.1f} (sub-dimensions detected)"
    else:
        schema_type = SchemaType.THREEF_NF
        desc = f"3NF: avg dim depth = {avg_depth:.1f} (deeply normalized)"

    return SchemaDefinition(
        name=name,
        schema_type=schema_type,
        tables=table_names,
        relationships=relationships,
        description=desc,
    )
