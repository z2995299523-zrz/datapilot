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
# CTE 链式 SQL 脚本生成 — 每个步骤一个 CTE，最终 SELECT 汇总
# ============================================================================

def generate_sql_script(
    pseudocode: PseudoCode,
    tables: dict[str, TableInfo] | None = None,
    assertions: list[Assertion] | None = None,
    unmatched_concepts: list[str] | None = None,
    requirement_summary: str = "",
    user_permissions: dict | None = None,
) -> str:
    """将伪代码编译为完整的 CTE 链式 SQL 脚本

    每个分析步骤生成一个 CTE (WITH ... AS)，步骤间通过 CTE 引用串联。
    顶部标注未确认的模型、字段、口径问题。

    Args:
        pseudocode: 分析伪代码
        tables: 数据字典表映射
        assertions: 断言条件列表（注入 WHERE 子句）
        unmatched_concepts: 未匹配到的概念（标注在文件头）
        requirement_summary: 需求摘要（用于文件头）

    Returns:
        完整的 SQL 脚本（含注释头 + CTE 链 + 最终 SELECT）
    """
    tables = tables or {}
    unmatched_concepts = unmatched_concepts or []

    # ── 文件头注释 ──
    header = _build_script_header(
        pseudocode=pseudocode,
        unmatched_concepts=unmatched_concepts,
        requirement_summary=requirement_summary,
        tables=tables,
    )

    if not pseudocode.steps:
        return header + "\n-- (无分析步骤，无法生成 SQL)\n"

    # ── 生成 CTE 链 ──
    cte_defs, final_select = _build_cte_chain(
        steps=pseudocode.steps,
        tables=tables,
        assertions=assertions,
        user_permissions=user_permissions,
    )

    return header + "\n" + cte_defs + "\n" + final_select


def _build_lineage_map(tables: dict[str, TableInfo]) -> dict[str, str]:
    """构建表→源系统映射，追踪数据血缘

    策略：
      1. 表显式声明了 source_system → 直接使用
      2. DM/DWS 表无 source_system → 通过 FK 链向下追踪到 ODS 层（最多 3 层）

    Returns:
        {table_name: source_system} — source_system 为空表示无法追踪
    """
    lineage: dict[str, str] = {}

    # Pass 1: 显式声明的 source_system
    for name, info in tables.items():
        if info.source_system:
            lineage[name] = info.source_system

    # Pass 2: FK 追踪（从高层追到 ODS 声明的源系统）
    def _trace(name: str, visited: set, depth: int) -> str:
        if depth <= 0 or name in visited:
            return ""
        visited.add(name)
        info = tables.get(name)
        if not info:
            return ""
        if info.source_system:
            return info.source_system
        # 沿 FK 向下追溯
        for col in info.columns:
            if col.referenced_table and col.referenced_table != name:
                ref_name = col.referenced_table
                # 尝试匹配完整表名
                for t_name in tables:
                    if t_name.lower() == ref_name.lower():
                        result = _trace(t_name, visited.copy(), depth - 1)
                        if result:
                            return result
                # 直接尝试
                result = _trace(ref_name, visited.copy(), depth - 1)
                if result:
                    return result
        return ""

    for name, info in tables.items():
        if name not in lineage:
            upstream = _trace(name, set(), depth=3)
            if upstream:
                lineage[name] = upstream

    return lineage


def _build_script_header(
    pseudocode: PseudoCode,
    unmatched_concepts: list[str],
    requirement_summary: str,
    tables: dict[str, TableInfo] | None = None,
) -> str:
    """构建 SQL 脚本顶部注释（含数据血缘）"""
    from datetime import datetime

    lines = []
    lines.append("-- " + "=" * 60)
    lines.append("--  DataPilot 分析 SQL 脚本")
    lines.append(f"--  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if pseudocode.title:
        lines.append(f"--  分析标题: {pseudocode.title}")
    if requirement_summary:
        summary_short = requirement_summary[:60].replace("\n", " ")
        lines.append(f"--  需求摘要: {summary_short}")
    lines.append("-- " + "=" * 60)

    # ── 数据血缘：源系统 → 表映射 ──
    if tables:
        lineage = _build_lineage_map(tables)
        # 收集脚本涉及的表及其源系统
        involved_tables: set[str] = set()
        for step in pseudocode.steps:
            src = _clean_table_name(step.source_table) if step.source_table else ""
            if src and src in tables:
                involved_tables.add(src)
            for j in step.joins:
                # 提取 JOIN 中引用的表名
                import re as _re2
                jt_match = _re2.match(r'(?:LEFT|RIGHT|INNER|FULL|CROSS)?\s*JOIN\s+(\w+)', j, _re2.IGNORECASE)
                if jt_match:
                    jt = jt_match.group(1)
                    if jt in tables:
                        involved_tables.add(jt)

        if involved_tables:
            # 按源系统分组
            system_tables: dict[str, list[str]] = {}
            unknown_tables: list[str] = []
            for t_name in sorted(involved_tables):
                sys = lineage.get(t_name, "")
                if sys:
                    system_tables.setdefault(sys, []).append(t_name)
                else:
                    unknown_tables.append(t_name)

            if system_tables or unknown_tables:
                lines.append("--")
                lines.append("--  🔗 数据血缘（源系统追踪）:")
                for sys_name in sorted(system_tables):
                    t_list = system_tables[sys_name]
                    lines.append(f"--    源系统: {sys_name}")
                    for t in t_list:
                        t_info = tables.get(t)
                        layer_tag = f"({t_info.layer.value}层)" if t_info else ""
                        comment_tag = f" — {t_info.table_comment}" if t_info and t_info.table_comment else ""
                        lines.append(f"--      ├─ {t} {layer_tag}{comment_tag}")
                if unknown_tables:
                    lines.append(f"--    ⚠ 未标注源系统: {', '.join(unknown_tables)}")
                lines.append("--")

    # 待确认事项
    issues: list[str] = []

    # 未匹配概念
    if unmatched_concepts:
        issues.append("以下概念未能匹配到数据字典字段，请人工确认:")
        for c in unmatched_concepts:
            issues.append(f"    - {c}")

    # 伪代码 TODO
    if pseudocode.todo_items:
        issues.append("伪代码生成的待确认事项:")
        for t in pseudocode.todo_items:
            issues.append(f"    - {t}")

    # 伪代码备注
    if pseudocode.notes:
        issues.append("备注:")
        for n in pseudocode.notes:
            issues.append(f"    - {n}")

    if issues:
        lines.append("--")
        lines.append("--  ⚠ 待确认事项:")
        for issue in issues:
            lines.append(f"--  {issue}")
    else:
        lines.append("--")
        lines.append("--  ✅ 无待确认事项")

    # 统计
    lines.append("--")
    lines.append(f"--  📊 计算步骤: {len(pseudocode.steps)} 步")
    lines.append(f"--  📊 未匹配概念: {len(unmatched_concepts)} 个" if unmatched_concepts else "--  📊 所有概念已匹配")
    lines.append("-- " + "=" * 60)

    return "\n".join(lines)


def _clean_table_name(name: str) -> str:
    """清理表名：去掉 LLM 混入的数据层标注等后缀

    例: "fact_velocity (DWS层)" → "fact_velocity"
         "v_customer_summary (DM层)" → "v_customer_summary"
    """
    import re
    # 去掉括号及内容：(DWS层) (DM层) (ODS层) 等
    return re.sub(r"\s*\([^)]*层\)\s*", "", name).strip()


def _get_known_columns(tables: dict[str, TableInfo]) -> dict[str, set[str]]:
    """构建 {table_name: {column_names}} 索引"""
    known: dict[str, set[str]] = {}
    for name, info in tables.items():
        known[name] = {c.name.lower() for c in info.columns}
    return known


def _validate_columns(
    output_cols: list[str],
    source_table: str,
    tables: dict[str, TableInfo],
) -> list[str]:
    """校验输出列是否在源表中存在，标注不存在的列"""
    clean_source = _clean_table_name(source_table)
    known = _get_known_columns(tables)
    table_cols = known.get(clean_source, set())

    validated: list[str] = []
    for col in output_cols:
        # 聚合函数/表达式 → 不校验
        if _looks_aggregate(col) or "(" in col or col == "*":
            validated.append(col)
            continue
        # 提取纯列名（去掉 table. 前缀）
        pure = col.split(".")[-1].strip().lower()
        if table_cols and pure not in table_cols:
            validated.append(f"{col}  -- ⚠ 列在 {clean_source} 中未找到")
        else:
            validated.append(col)
    return validated


def _build_cte_chain(
    steps: list,
    tables: dict[str, TableInfo],
    assertions: list | None,
    user_permissions: dict | None = None,
) -> tuple[str, str]:
    """构建 CTE 链 — 每个步骤一个自包含 CTE，用实际源表不硬链

    策略:
      - 每步使用自己的 source_table（不强行引用前一步 CTE）
      - 仅当步骤无 source_table 且前一步有明确的输出列时，才引用前一步 CTE
      - 表名清理（去掉 LLM 混入的层标注）
      - 列存在性校验
      - 数据血缘标注（源系统追踪）
    """
    # 构建血缘映射
    lineage = _build_lineage_map(tables) if tables else {}

    cte_blocks: list[str] = []
    prev_cte_name: str | None = None
    prev_output_cols: list[str] = []

    for i, step in enumerate(steps):
        cte_name = f"step_{step.step_number:02d}"
        clean_source = _clean_table_name(step.source_table) if step.source_table else ""

        # ── 中文步骤引用翻译: "步骤5结果" → "step_05" ──
        import re as _re
        step_ref = _re.search(r'步骤\s*(\d+)(?:结果|输出)?', clean_source)
        if step_ref:
            num = int(step_ref.group(1))
            clean_source = f"step_{num:02d}"

        has_source = bool(clean_source and clean_source != "unknown_table")

        # 确定 FROM 来源
        if has_source:
            source = clean_source
            use_prev = False
        elif prev_cte_name and prev_output_cols:
            # 无源表 → 从前一步 CTE 读取（过滤/聚合步骤）
            source = prev_cte_name
            use_prev = True
            has_source = True  # 有来源了（来自前一步）
        else:
            # 实在没有来源，跳过
            source = "unknown_table"
            use_prev = False

        # 源系统（血缘）
        source_sys = lineage.get(clean_source, "") if not use_prev else ""

        # SELECT 列
        if step.output:
            output_cols = _parse_output_columns(step.output)
        elif use_prev:
            output_cols = list(prev_output_cols)
        else:
            output_cols = ["*"]

        # 列校验
        if tables:
            output_cols = _validate_columns(output_cols, clean_source if not use_prev else "", tables)

        # 聚合列 + 非聚合列
        agg_cols = [c for c in output_cols if _looks_aggregate(c)]
        non_agg_cols = [c for c in output_cols if not _looks_aggregate(c) and c != "*"]

        # 构建 CTE
        lines = [f"{cte_name} AS ("]
        lines.append("    SELECT")
        for j, col in enumerate(output_cols):
            suffix = "," if j < len(output_cols) - 1 else ""
            lines.append(f"        {col}{suffix}")

        # 血缘注释
        if source_sys:
            lines.append(f"    FROM {source}  -- 来源系统: {source_sys}")
        else:
            lines.append(f"    FROM {source}")

        # JOIN
        if not use_prev:
            for j in step.joins:
                clean_join = _clean_join_clause(j, source_table=source, prev_cte=prev_cte_name)
                # 给 JOIN 的表也标注血缘
                jt_sys = _extract_join_source_system(j, lineage, tables)
                if jt_sys:
                    clean_join += f"  -- 来源系统: {jt_sys}"
                lines.append(f"    {clean_join}")
        elif step.joins:
            # 引用前一步 CTE 但仍有 JOIN → JOIN 的是其他 CTE/表
            for j in step.joins:
                clean_join = _clean_join_clause(j, source_table="", prev_cte=source)
                jt_sys = _extract_join_source_system(j, lineage, tables)
                if jt_sys:
                    clean_join += f"  -- 来源系统: {jt_sys}"
                lines.append(f"    {clean_join}")

        # WHERE
        where_clauses = list(step.conditions)
        if assertions:
            for a in assertions:
                if a.type.value == "code" and not _assertion_already_covered(a, where_clauses):
                    where_clauses.append(a.sql_condition)

        # ── 部门权限过滤：注入 WHERE dept_column IN (...) ──
        if (user_permissions and not user_permissions.get("is_admin")
                and not use_prev and clean_source in tables):
            visible_dept_ids = user_permissions.get("visible_dept_ids", [])
            if visible_dept_ids:
                from auth.database import get_session
                from auth.models import TableDeptColumn
                with get_session() as session:
                    tdc = session.query(TableDeptColumn).filter(
                        TableDeptColumn.table_name == clean_source
                    ).first()
                if tdc:
                    ids_str = ", ".join(repr(str(did)) for did in visible_dept_ids)
                    dept_filter = f"{clean_source}.{tdc.dept_column} IN ({ids_str})"
                    if dept_filter not in where_clauses:
                        where_clauses.append(dept_filter)

        if where_clauses:
            unique_where = list(dict.fromkeys(where_clauses))
            lines.append("    WHERE " + "\n        AND ".join(unique_where))

        # GROUP BY
        if step.aggregations and non_agg_cols:
            gb_cols = [c for c in non_agg_cols if "*" not in c and "⚠" not in c]
            if gb_cols:
                lines.append("    GROUP BY " + ", ".join(gb_cols))

        lines.append(")")

        comment = f"-- 步骤 {step.step_number}: {step.description}"
        cte_blocks.append(f"{comment}\n" + "\n".join(lines))

        prev_cte_name = cte_name
        prev_output_cols = output_cols

    # 组装 WITH
    cte_defs = "WITH\n" + ",\n\n".join(cte_blocks)

    # 最终 SELECT
    last_cte = f"step_{steps[-1].step_number:02d}"
    final_step = steps[-1]

    final_lines = ["-- ============================================================",
                   "--  最终输出",
                   "-- ============================================================"]
    if final_step.output:
        output_cols = _parse_output_columns(final_step.output)
        final_lines.append("SELECT")
        for j, col in enumerate(output_cols):
            suffix = "," if j < len(output_cols) - 1 else ""
            final_lines.append(f"    {col}{suffix}")
    else:
        final_lines.append("SELECT *")
    final_lines.append(f"FROM {last_cte};")

    return cte_defs, "\n".join(final_lines)


def _clean_join_clause(join: str, source_table: str = "", prev_cte: str = "") -> str:
    """清理 JOIN 子句，并补全 LLM 遗漏的语法

    处理三种不规范的 LLM 产物:
      1. 裸条件: "table1.col = table2.col" → "LEFT JOIN table2 ON table1.col = table2.col"
      2. 中文步骤引用: "LEFT JOIN 步骤6结果 ON account_id" → "LEFT JOIN step_06 ON step_05.account_id = step_06.account_id"
      3. 残缺 ON: "LEFT JOIN table ON col" → "LEFT JOIN table ON source.col = table.col"
    """
    import re

    join = join.strip()

    # ── 替换中文步骤引用 ──
    # "步骤5结果" / "步骤5" / "步骤05" → "step_05"
    def _translate_step_ref(text: str) -> str:
        m = re.search(r'步骤\s*(\d+)(?:结果|输出)?', text)
        if m:
            num = int(m.group(1))
            old = m.group(0)
            new = f"step_{num:02d}"
            return text.replace(old, new)
        return text

    join = _translate_step_ref(join)

    # ── 检查是否已有 JOIN 关键字 ──
    has_join_keyword = bool(re.match(
        r'^(LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|FULL\s+JOIN|CROSS\s+JOIN|JOIN)\s+',
        join, re.IGNORECASE
    ))

    if has_join_keyword:
        # 已有 JOIN，检查 ON 是否残缺（只有一个列名，不是完整条件）
        on_match = re.search(r'\bON\s+(.+)$', join, re.IGNORECASE)
        if on_match:
            on_clause = on_match.group(1).strip()
            # 如果 ON 后面只是一个列名（无 = 等操作符）
            if not re.search(r'[=<>]', on_clause):
                col = on_clause.strip()
                # 补全: ON source_table.col = joined_table.col
                # 提取被 JOIN 的表名
                table_match = re.match(r'(LEFT\s+JOIN|JOIN)\s+(\w+)', join, re.IGNORECASE)
                if table_match and source_table:
                    joined_table = table_match.group(2)
                    new_on = f"{source_table}.{col} = {joined_table}.{col}"
                    join = re.sub(r'\bON\s+.+$', f"ON {new_on}", join, flags=re.IGNORECASE)
                elif table_match and prev_cte:
                    joined_table = table_match.group(2)
                    new_on = f"{prev_cte}.{col} = {joined_table}.{col}"
                    join = re.sub(r'\bON\s+.+$', f"ON {new_on}", join, flags=re.IGNORECASE)
        return join

    # ── 裸条件: "table1.col = table2.col" → "LEFT JOIN table2 ON ..." ──
    # 已知 source_table，从条件中提取另一个表
    if source_table:
        # 尝试匹配 table.column = other_table.column 模式
        cond_match = re.match(r'(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)', join)
        if cond_match:
            t1, c1, t2, c2 = cond_match.groups()
            # 确定哪个是 source，哪个是 joined
            if t1.lower() == source_table.lower():
                joined_table, joined_col = t2, c2
                source_col = c1
            else:
                joined_table, joined_col = t1, c1
                source_col = c2
            return f"LEFT JOIN {joined_table} ON {source_table}.{source_col} = {joined_table}.{joined_col}"

    # 无法识别 → 保持原样（标注警告）
    return f"{join}  -- ⚠ JOIN 格式异常，请人工检查"


def _extract_join_source_system(
    join: str,
    lineage: dict[str, str],
    tables: dict[str, TableInfo],
) -> str:
    """从 JOIN 子句中提取被关联表的源系统名称"""
    import re as _re3
    # 匹配 JOIN table_name 模式
    m = _re3.match(r'(?:LEFT|RIGHT|INNER|FULL|CROSS)?\s*JOIN\s+(\w+)', join, _re3.IGNORECASE)
    if m:
        jt = m.group(1)
        # 查血缘映射
        if jt in lineage and lineage[jt]:
            return lineage[jt]
        # 尝试模糊匹配（大小写不敏感）
        for t_name, sys_name in lineage.items():
            if t_name.lower() == jt.lower() and sys_name:
                return sys_name
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
