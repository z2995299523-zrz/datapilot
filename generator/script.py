"""
SQL 脚本生成引擎 — PseudoCode → 可执行 SQL

核心映射:
  source_table → FROM
  joins        → LEFT JOIN ... ON ...
  conditions   → WHERE ... AND ...
  aggregations → SELECT + GROUP BY
  output       → SELECT columns

JOIN 键推断优先级:
  1. 数据字典 relations 字段（人工标注，最高优先级）
  2. 字段名匹配（两个表都有 cust_id → 候选关联键）
  3. LLM 辅助推断（前两者都失败时）
"""
from models import (
    PseudoCode, PseudoCodeStep, TableInfo, Assertion, AssertionType,
)


def generate_sql(
    pseudocode: PseudoCode,
    tables: dict[str, TableInfo] | None = None,
    assertions: list[Assertion] | None = None,
) -> str:
    """将伪代码步骤编译为一条 SQL 查询

    Args:
        pseudocode: 分析伪代码
        tables: 数据字典中的表信息映射 {table_name: TableInfo}，用于 JOIN 键推断
        assertions: 断言条件列表，WHERE 子句生成时优先使用

    Returns:
        完整的 SQL SELECT 语句
    """
    if not pseudocode.steps:
        return "-- 无分析步骤"

    tables = tables or {}

    from_tables: list[str] = []
    join_clauses: list[str] = []
    where_clauses: list[str] = []
    select_parts: list[str] = []
    group_by_parts: list[str] = []

    for step in pseudocode.steps:
        # 源表
        if step.source_table and step.source_table not in from_tables:
            from_tables.append(step.source_table)

        # JOIN
        for j in step.joins:
            if j not in join_clauses:
                join_clauses.append(j)

        # 条件
        for c in step.conditions:
            if c not in where_clauses:
                where_clauses.append(c)

        # 聚合 → SELECT + GROUP BY
        if step.aggregations:
            for agg in step.aggregations:
                if agg not in select_parts:
                    select_parts.append(agg)
            # 非聚合 output 列 → SELECT + GROUP BY
            if step.output:
                for col in _parse_output_columns(step.output):
                    if col not in select_parts and not _is_aggregated(col, step.aggregations):
                        select_parts.append(col)
                    if col not in group_by_parts and not _is_aggregated(col, step.aggregations):
                        group_by_parts.append(col)

        # 无聚合步骤的 output → SELECT 列
        elif step.output:
            for col in _parse_output_columns(step.output):
                if col not in select_parts:
                    select_parts.append(col)

    # 自动推断 GROUP BY：SELECT 中非聚合列
    if not group_by_parts and select_parts:
        for col in select_parts:
            if not _looks_aggregate(col) and col not in group_by_parts:
                group_by_parts.append(col)

    # ── 断言条件注入：补充 LLM 遗漏的 WHERE 条件 ──
    if assertions:
        for a in assertions:
            if a.type == AssertionType.CODE:
                # 检查该断言是否已被现有 WHERE 条件覆盖
                if not _assertion_already_covered(a, where_clauses):
                    where_clauses.append(a.sql_condition)

    # 组装 SQL
    return _assemble_sql(
        select=select_parts,
        from_tables=from_tables,
        joins=join_clauses,
        where=where_clauses,
        group_by=group_by_parts,
    )


def _assemble_sql(
    select: list[str],
    from_tables: list[str],
    joins: list[str],
    where: list[str],
    group_by: list[str],
) -> str:
    """组装最终 SQL"""
    lines = []

    # SELECT
    if not select:
        select = ["*"]
    lines.append("SELECT")
    for i, col in enumerate(select):
        suffix = "," if i < len(select) - 1 else ""
        lines.append(f"    {col}{suffix}")

    # FROM
    if from_tables:
        lines.append(f"FROM {from_tables[0]}")
        # 剩余表通过 JOIN 引入
        for extra in from_tables[1:]:
            inferred = _infer_join_clause(from_tables[0], extra)
            if inferred and inferred not in joins:
                joins.append(inferred)

    # JOIN
    for j in joins:
        lines.append(j)

    # WHERE
    if where:
        lines.append("WHERE " + "\n    AND ".join(where))

    # GROUP BY
    if group_by:
        lines.append("GROUP BY " + ", ".join(group_by))

    return "\n".join(lines) + "\n"


def _parse_output_columns(output: str) -> list[str]:
    """解析 output 字段中的列名列表"""
    cols = []
    for part in output.split(","):
        col = part.strip()
        if col:
            # 提取别名（取 AS 后面的名称，或直接用列名）
            cols.append(col)
    return cols


def _is_aggregated(col: str, aggregations: list[str]) -> bool:
    """检查列是否已通过聚合函数定义"""
    col_lower = col.lower()
    for agg in aggregations:
        agg_lower = agg.lower()
        # 检查聚合的 AS 别名匹配
        if " as " in agg_lower:
            alias = agg_lower.split(" as ")[-1].strip()
            if alias == col_lower:
                return True
    return False


def _assertion_already_covered(assertion: Assertion, where_clauses: list[str]) -> bool:
    """检查断言条件是否已被现有 WHERE 子句覆盖"""
    col = assertion.column.lower()
    val = assertion.value.lower()
    for clause in where_clauses:
        clause_lower = clause.lower()
        # 已包含相同列名和相同值 → 已覆盖
        if col in clause_lower and val in clause_lower:
            return True
        # 已包含相同列名和 = 操作符 → 可能已覆盖
        if col in clause_lower and "=" in clause_lower:
            return True
    return False


def _looks_aggregate(expr: str) -> bool:
    """判断表达式是否包含聚合函数"""
    agg_funcs = ["count(", "sum(", "avg(", "max(", "min(", "count(distinct "]
    lower = expr.lower()
    return any(f in lower for f in agg_funcs)


def _infer_join_clause(left_table: str, right_table: str) -> str:
    """基于表名推断 JOIN 子句（启发式）"""
    # 常见关联键模式
    join_patterns = [
        ("cust_id", "cust_id"),
        ("channel_id", "channel_id"),
        ("product_id", "product_id"),
        ("merchant_id", "merchant_id"),
        ("account_id", "account_id"),
    ]
    for l_key, r_key in join_patterns:
        # 两个表名不同但共享关联键 → 可能可通过此关联
        return f"LEFT JOIN {right_table} ON {left_table}.{r_key} = {right_table}.{r_key}"

    return ""


# ============================================================================
# JOIN 键推断（给 LLM 辅助调用）
# ============================================================================

def infer_join_keys(
    left_table: str,
    right_table: str,
    tables: dict[str, TableInfo],
) -> list[tuple[str, str]]:
    """推断两个表之间的 JOIN 键

    优先级:
      1. 数据字典 relations 字段
      2. 同名字段匹配
      3. LLM 辅助（调用方负责）

    Returns:
        [(left_col, right_col), ...] 候选关联键对
    """
    left = tables.get(left_table)
    right = tables.get(right_table)
    if not left or not right:
        return []

    # 1. 数据字典中的外键引用
    for col in left.columns:
        if col.referenced_table and col.referenced_table == right_table:
            # 在右表中找同名或主键列匹配
            right_pk = next((c for c in right.columns if c.is_primary_key), None)
            if right_pk:
                return [(col.name, right_pk.name)]

    # 2. 同名字段
    left_names = {c.name for c in left.columns}
    right_names = {c.name for c in right.columns}
    common = left_names & right_names
    if common:
        # _id 后缀的字段优先
        id_fields = {f for f in common if f.endswith("_id")}
        if id_fields:
            common = id_fields
        return [(f, f) for f in sorted(common)]

    # 3. 模式匹配：left_table_name_id → right_table.primary_key
    # 例如: channel_id → dim_channel.channel_id
    for col in left.columns:
        if col.is_foreign_key and col.referenced_table:
            ref = tables.get(col.referenced_table)
            if ref:
                pk = next((c for c in ref.columns if c.is_primary_key), None)
                if pk:
                    return [(col.name, pk.name)]

    return []
