"""
L2 逻辑结果比对 — SQL 生成模式

设计原则：
  比对逻辑写入 SQL，两个结果集在数据库内完成 diff，不拉到 Python 内存。

  - 行数比对: SELECT COUNT(*) from both sides
  - 全量 diff: LEFT JOIN + WHERE NULL (missing/extra) + INNER JOIN + 逐列比对 (value_diff)
  - 聚合一致性: detail GROUP BY vs summary 值
  - Schema 比对: 元数据层检查（Python）

所有 diff 子查询统一为 4 列: (diff_type, key_values, column_name, detail)
"""
from pydantic import BaseModel, Field


class ComparisonResult(BaseModel):
    check_type: str = Field(...)
    passed: bool
    detail: str = ""
    actual_value: str = ""
    expected_value: str = ""


class ComparisonReport(BaseModel):
    expected_rows: int = 0
    actual_rows: int = 0
    checks: list[ComparisonResult] = Field(default_factory=list)
    passed_count: int = 0
    failed_count: int = 0
    overall_passed: bool = True

    def model_post_init(self, __context):
        self.passed_count = sum(1 for c in self.checks if c.passed)
        self.failed_count = sum(1 for c in self.checks if not c.passed)
        self.overall_passed = self.failed_count == 0


D1, D2, D3, D4 = "diff_type", "key_values", "col_name", "detail"


def generate_row_count_compare_sql(expected_sql: str, actual_sql: str) -> str:
    """返回两边的行数"""
    return f"""
SELECT 'expected' AS source, COUNT(*) AS row_count FROM ({expected_sql}) _e
UNION ALL
SELECT 'actual' AS source, COUNT(*) AS row_count FROM ({actual_sql}) _a
"""


def generate_full_diff_sql(
    expected_sql: str,
    actual_sql: str,
    key_columns: list[str],
    compare_columns: list[str] | None = None,
) -> str:
    """生成全量 diff SQL — 统一 4 列 schema: diff_type, key_values, col_name, detail"""
    keys = key_columns
    join = "\n    AND ".join(f"_e.{k} = _a.{k}" for k in keys)
    key_concat = " || '|' || ".join(f"CAST(_e.{k} AS VARCHAR)" for k in keys)
    key_concat_a = " || '|' || ".join(f"CAST(_a.{k} AS VARCHAR)" for k in keys)
    null_check = " OR ".join(f"_a.{k} IS NULL" for k in keys)
    null_check_e = " OR ".join(f"_e.{k} IS NULL" for k in keys)

    queries = []

    # missing
    queries.append(f"""SELECT
    'missing' AS {D1},
    {key_concat} AS {D2},
    NULL AS {D3},
    NULL AS {D4}
FROM ({expected_sql}) _e
LEFT JOIN ({actual_sql}) _a ON {join}
WHERE {null_check}""")

    # extra
    queries.append(f"""SELECT
    'extra' AS {D1},
    {key_concat_a} AS {D2},
    NULL AS {D3},
    NULL AS {D4}
FROM ({actual_sql}) _a
LEFT JOIN ({expected_sql}) _e ON {join}
WHERE {null_check_e}""")

    # value_diff
    if compare_columns:
        for col in compare_columns:
            queries.append(f"""SELECT
    'value_diff' AS {D1},
    {key_concat} AS {D2},
    '{col}' AS {D3},
    'exp:' || COALESCE(CAST(_e.{col} AS VARCHAR), 'NULL') || ' act:' || COALESCE(CAST(_a.{col} AS VARCHAR), 'NULL') AS {D4}
FROM ({expected_sql}) _e
INNER JOIN ({actual_sql}) _a ON {join}
WHERE _e.{col} != _a.{col}
   OR (_e.{col} IS NULL AND _a.{col} IS NOT NULL)
   OR (_e.{col} IS NOT NULL AND _a.{col} IS NULL)""")

    return "\nUNION ALL\n".join(queries) + f"\nORDER BY {D1}, {D2}\n"


def generate_aggregation_check_sql(
    detail_sql: str,
    summary_sql: str,
    agg_specs: list[dict],
) -> str:
    """生成聚合一致性检查 SQL"""
    parts = []
    for spec in agg_specs:
        group_cols = spec.get("group_cols", [])
        agg_col = spec["agg_col"]
        agg_func = spec["agg_func"].upper()
        summary_col = spec.get("summary_col", agg_col)
        func_map = {"SUM": "SUM", "COUNT": "COUNT", "AVG": "AVG", "MAX": "MAX", "MIN": "MIN"}
        sql_func = func_map.get(agg_func, "SUM")

        if group_cols:
            g_select = ", ".join(group_cols)
            g_key = " || '|' || ".join(f"CAST(d.{c} AS VARCHAR)" for c in group_cols)
            join_on = " AND ".join(f"d.{c} = s.{c}" for c in group_cols)
        else:
            g_select = "'__total__'"
            g_key = "'__total__'"
            join_on = "1=1"

        parts.append(f"""SELECT
    'aggregation' AS {D1},
    {g_key} AS {D2},
    '{agg_func}({agg_col})' AS {D3},
    'detail:' || CAST(d._agg_val AS VARCHAR) || ' summary:' || CAST(s.{summary_col} AS VARCHAR) || ' diff:' || CAST(ROUND(ABS(d._agg_val - s.{summary_col}) * 100.0 / NULLIF(ABS(s.{summary_col}), 0), 2) AS VARCHAR) || '%' AS {D4}
FROM (
    SELECT {g_select},
           {sql_func}({agg_col}) AS _agg_val
    FROM ({detail_sql}) _detail
    GROUP BY {g_select}
) d
LEFT JOIN ({summary_sql}) s ON {join_on}
WHERE s.{summary_col} IS NULL
   OR ABS(d._agg_val - COALESCE(s.{summary_col}, 0)) > 0.01""")

    return "\nUNION ALL\n".join(parts)


# ============================================================================
# Schema 比对（元数据 → Python）
# ============================================================================

def compare_schema(expected_columns: list[str], actual_columns: list[str]) -> ComparisonResult:
    exp_set = set(expected_columns)
    act_set = set(actual_columns)
    missing = exp_set - act_set
    extra = act_set - exp_set
    if not missing and not extra:
        return ComparisonResult(check_type="schema", passed=True,
                                detail=f"列结构一致: {len(expected_columns)} 列",
                                actual_value=", ".join(actual_columns),
                                expected_value=", ".join(expected_columns))
    parts = []
    if missing: parts.append(f"缺失: {', '.join(sorted(missing))}")
    if extra: parts.append(f"多余: {', '.join(sorted(extra))}")
    return ComparisonResult(check_type="schema", passed=False, detail="; ".join(parts),
                            actual_value=", ".join(actual_columns),
                            expected_value=", ".join(expected_columns))


# ============================================================================
# 一键执行
# ============================================================================

def run_comparison_tests(
    conn,
    expected_sql: str,
    actual_sql: str,
    key_columns: list[str] | None = None,
    compare_columns: list[str] | None = None,
    agg_specs: list[dict] | None = None,
    summary_sql: str | None = None,
    max_diff_pct: float = 0.0,
) -> ComparisonReport:
    """一键执行 L2 比对"""
    checks: list[ComparisonResult] = []

    # 行数
    try:
        cur = conn.execute(generate_row_count_compare_sql(expected_sql, actual_sql))
        counts = {r[0]: r[1] for r in cur.fetchall()}
        exp_count = counts.get("expected", 0)
        act_count = counts.get("actual", 0)
    except Exception as e:
        return ComparisonReport(checks=[
            ComparisonResult(check_type="execution_error", passed=False,
                             detail=f"行数查询失败: {e}")])

    # schema
    try:
        cur = conn.execute(f"SELECT * FROM ({expected_sql}) WHERE 1=0")
        exp_cols = [d[0] for d in cur.description] if cur.description else []
        cur = conn.execute(f"SELECT * FROM ({actual_sql}) WHERE 1=0")
        act_cols = [d[0] for d in cur.description] if cur.description else []
        checks.append(compare_schema(exp_cols, act_cols))
    except Exception:
        pass

    # 行数比对
    diff = abs(act_count - exp_count)
    pct = diff / max(exp_count, 1)
    checks.append(ComparisonResult(
        check_type="row_count",
        passed=pct <= max_diff_pct,
        detail=f"{'一致' if pct <= max_diff_pct else '不一致'}: 预期 {exp_count}，实际 {act_count}",
        actual_value=f"{act_count} 行",
        expected_value=f"{exp_count} 行",
    ))

    # 全量 diff
    if key_columns:
        try:
            sql = generate_full_diff_sql(expected_sql, actual_sql, key_columns, compare_columns)
            rows = conn.execute(sql).fetchall()
            by_type = _group(rows)
            m = len(by_type.get("missing", []))
            e = len(by_type.get("extra", []))
            v = len(by_type.get("value_diff", []))
            t = m + e + v
            if t == 0:
                checks.append(ComparisonResult(check_type="full_diff", passed=True,
                                detail="数据完全一致", actual_value="0 差异", expected_value="0 差异"))
            else:
                parts = []
                if m: parts.append(f"{m} 行缺失")
                if e: parts.append(f"{e} 行多余")
                if v: parts.append(f"{v} 处值差异")
                checks.append(ComparisonResult(check_type="full_diff", passed=False,
                                detail="，".join(parts), actual_value=f"差异 {t} 处", expected_value="0 差异"))
        except Exception as ex:
            checks.append(ComparisonResult(check_type="full_diff", passed=False,
                            detail=f"全量 diff 执行失败: {ex}"))

    # 聚合一致性
    if agg_specs and summary_sql:
        try:
            sql = generate_aggregation_check_sql(actual_sql, summary_sql, agg_specs)
            rows = conn.execute(sql).fetchall()
            if rows:
                checks.append(ComparisonResult(check_type="aggregation", passed=False,
                                detail=f"{len(rows)} 处分组聚合不一致",
                                actual_value="; ".join(str(r[3]) for r in rows[:5]),
                                expected_value="明细聚合 = 汇总值"))
            else:
                checks.append(ComparisonResult(check_type="aggregation", passed=True,
                                detail="聚合值全部一致", actual_value="一致",
                                expected_value="明细聚合 = 汇总值"))
        except Exception as ex:
            checks.append(ComparisonResult(check_type="aggregation", passed=False,
                            detail=f"聚合检查失败: {ex}"))

    return ComparisonReport(expected_rows=exp_count, actual_rows=act_count, checks=checks)


def _group(rows: list[tuple]) -> dict[str, list[tuple]]:
    g: dict[str, list[tuple]] = {}
    for r in rows:
        g.setdefault(r[0] if r else "", []).append(r)
    return g
