"""
L1 基础数据质量测试 — SQL 生成模式

设计原则：
  原始 SQL 被包成 CTE (_source)，检查逻辑写成 SELECT 语句在数据库内执行。
  数据库只返回违规行，不做大规模数据传输。

  错误做法: SQL → Python load 1000万行 → for row in rows: check → O(n) 内存爆炸
  正确做法: SQL → WRAP AS CTE → test SQL → DB 执行 → 只返回 3 行违规 → O(1)

所有检查子查询统一为 5 列 schema:
  (check_type, column_name, value1, value2, value3)
保证 UNION ALL 可行，parse_test_results 按 check_type 分派解析。

用法：
  from testing.quality import generate_all_checks_sql, run_quality_tests
  import sqlite3
  conn = sqlite3.connect(":memory:")
  test_sql = generate_all_checks_sql(original_sql, column_infos)
  rows = conn.execute(test_sql).fetchall()   # 只返回违规行
  report = parse_test_results(rows, column_infos)
"""
import itertools
import re
from math import prod
from typing import Optional

from pydantic import BaseModel, Field
from models import ColumnInfo, CodeMapping


# ============================================================================
# 结果模型
# ============================================================================

class QualityCheckResult(BaseModel):
    check_type: str = Field(...)
    column: str = Field(default="")
    passed: bool = Field(...)
    detail: str = Field(default="")
    actual_value: str = Field(default="")
    expected_value: str = Field(default="")


class QualityReport(BaseModel):
    total_rows: int = 0
    total_columns: int = 0
    checks: list[QualityCheckResult] = Field(default_factory=list)
    passed_count: int = 0
    failed_count: int = 0
    overall_passed: bool = True

    def model_post_init(self, __context):
        self.passed_count = sum(1 for c in self.checks if c.passed)
        self.failed_count = sum(1 for c in self.checks if not c.passed)
        self.overall_passed = self.failed_count == 0


CTE_NAME = "_source"

# 统一列 schema 的列别名
C1, C2, C3, C4, C5 = "check_type", "column_name", "v1", "v2", "v3"


def _cte(original_sql: str) -> str:
    """生成顶层 CTE 包装"""
    sql = original_sql.rstrip().rstrip(";").rstrip()
    return f"WITH {CTE_NAME} AS (\n{sql}\n)"


wrap_as_cte = _cte  # 对外别名


def generate_null_rate_sql(original_sql: str, columns: list[str]) -> str:
    """生成空值率检查 SQL（对外，含 CTE 包装）"""
    if not columns:
        return ""
    queries = [_null_sql(col) for col in columns]
    return _cte(original_sql) + "\n" + "\nUNION ALL\n".join(queries)


def generate_field_length_sql(original_sql: str, column_infos: list[ColumnInfo]) -> str:
    """生成字段超长检查 SQL（对外，含 CTE 包装）"""
    queries = []
    for ci in column_infos:
        q = _length_sql(ci)
        if q:
            queries.append(q)
    if not queries:
        return ""
    return _cte(original_sql) + "\n" + "\nUNION ALL\n".join(queries)


def generate_code_compliance_sql(original_sql: str, column: str, valid_codes: list[str]) -> str:
    """生成码值合规检查 SQL（对外，含 CTE 包装）"""
    if not valid_codes:
        return ""
    q = _code_sql(column, valid_codes)
    if not q:
        return ""
    return _cte(original_sql) + "\n" + q


# ============================================================================
# 内部：不含 CTE 的 SQL 片段（给 generate_all_checks_sql 复用单 CTE）
# ============================================================================

def generate_pk_uniqueness_sql(original_sql: str, pk_columns: list[str]) -> str:
    """生成主键唯一性检查 SQL（不包含 CTE 包装，由 generate_all_checks_sql 统一包装）"""
    if not pk_columns:
        return ""
    return _cte(original_sql) + "\n" + _pk_sql(pk_columns)


def _pk_sql(pk_columns: list[str]) -> str:
    """主键唯一性 → 返回重复行的主键值（内部，无 CTE）"""
    if not pk_columns:
        return ""
    cols = ", ".join(pk_columns)
    return f"""SELECT
    'pk_uniqueness' AS {C1},
    '{'+'.join(pk_columns)}' AS {C2},
    {cols} AS {C3},
    CAST(COUNT(*) AS TEXT) AS {C4},
    NULL AS {C5}
FROM {CTE_NAME}
GROUP BY {cols}
HAVING COUNT(*) > 1"""


def _null_sql(col: str) -> str:
    """空值率 → 返回单列统计"""
    return f"""SELECT
    'null_rate' AS {C1},
    '{col}' AS {C2},
    CAST(COUNT(*) AS TEXT) AS {C3},
    CAST(SUM(CASE WHEN {col} IS NULL OR {col} = '' THEN 1 ELSE 0 END) AS TEXT) AS {C4},
    CAST(ROUND(SUM(CASE WHEN {col} IS NULL OR {col} = '' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2) AS TEXT) AS {C5}
FROM {CTE_NAME}"""


def _length_sql(ci: ColumnInfo) -> str:
    """字段超长 → 返回超长行的实际长度"""
    max_len = _parse_max_length(ci.data_type)
    if max_len is None:
        return ""
    return f"""SELECT
    'field_length' AS {C1},
    '{ci.name}' AS {C2},
    CAST(LENGTH(CAST({ci.name} AS VARCHAR)) AS TEXT) AS {C3},
    '{max_len}' AS {C4},
    SUBSTR(CAST({ci.name} AS VARCHAR), 1, 50) AS {C5}
FROM {CTE_NAME}
WHERE {ci.name} IS NOT NULL AND LENGTH(CAST({ci.name} AS VARCHAR)) > {max_len}"""


def _code_sql(col: str, valid_codes: list[str]) -> str:
    """码值合规 → 返回非法码值及出现次数"""
    if not valid_codes:
        return ""
    codes_str = ", ".join(f"'{c}'" for c in valid_codes)
    return f"""SELECT
    'code_compliance' AS {C1},
    '{col}' AS {C2},
    CAST({col} AS VARCHAR) AS {C3},
    CAST(COUNT(*) AS TEXT) AS {C4},
    NULL AS {C5}
FROM {CTE_NAME}
WHERE {col} IS NOT NULL
  AND CAST({col} AS VARCHAR) NOT IN ({codes_str})
  AND CAST({col} AS VARCHAR) != ''
GROUP BY CAST({col} AS VARCHAR)"""


# ============================================================================
# 聚合生成
# ============================================================================

def generate_all_checks_sql(
    original_sql: str,
    column_infos: list[ColumnInfo],
    pk_columns: list[str] | None = None,
    check_code_values: bool = True,
) -> str:
    """生成全套 L1 检查 SQL（一条语句，一次提交）

    所有子查询统一为 5 列 schema，用 UNION ALL 串联。
    """
    if pk_columns is None:
        pk_columns = [ci.name for ci in column_infos if ci.is_primary_key]
    col_names = [ci.name for ci in column_infos]

    queries = []

    # 1. 主键唯一性
    q = _pk_sql(pk_columns)
    if q:
        queries.append(q)

    # 2. 空值率（每列）
    for col in col_names:
        queries.append(_null_sql(col))

    # 3. 字段超长
    for ci in column_infos:
        q = _length_sql(ci)
        if q:
            queries.append(q)

    # 4. 码值合规
    if check_code_values:
        for ci in column_infos:
            if ci.code_values:
                q = _code_sql(ci.name, [c.value for c in ci.code_values])
                if q:
                    queries.append(q)

    if not queries:
        return "-- 无需检查"

    return _cte(original_sql) + "\n" + "\nUNION ALL\n".join(queries) + f"\nORDER BY {C1}, {C2}\n"


def generate_row_count_sql(original_sql: str) -> str:
    """生成行数查询"""
    return _cte(original_sql) + f"\nSELECT COUNT(*) AS total_rows FROM {CTE_NAME}"


# ============================================================================
# 结果解析
# ============================================================================

def parse_test_results(
    rows: list[tuple],
    column_infos: list[ColumnInfo],
    pk_columns: list[str] | None = None,
    max_null_rate: float = 0.10,
    expected_row_count: int = 0,
) -> QualityReport:
    """将 SQL 测试结果（统一 5 列 schema）解析为 QualityReport"""
    checks: list[QualityCheckResult] = []
    results = _group(rows)
    col_names = [ci.name for ci in column_infos]
    if pk_columns is None:
        pk_columns = [ci.name for ci in column_infos if ci.is_primary_key]

    # ── 主键唯一性 ──
    pk_rows = results.get("pk_uniqueness", [])
    if pk_columns:
        if pk_rows:
            dup_count = sum(int(r[3] or 0) for r in pk_rows)
            checks.append(QualityCheckResult(
                check_type="pk_uniqueness", column="+".join(pk_columns),
                passed=False,
                detail=f"发现 {len(pk_rows)} 组主键重复（{dup_count} 行）",
                actual_value=f"重复 {len(pk_rows)} 组",
                expected_value="全部唯一",
            ))
        else:
            checks.append(QualityCheckResult(
                check_type="pk_uniqueness", column="+".join(pk_columns),
                passed=True,
                detail="主键全部唯一",
                actual_value="0 重复", expected_value="0 重复",
            ))
    else:
        checks.append(QualityCheckResult(
            check_type="pk_uniqueness", passed=True,
            detail="未指定主键列，跳过",
        ))

    # ── 空值率 ──
    null_rows = results.get("null_rate", [])
    checked_null = {r[1] for r in null_rows}
    for r in null_rows:
        col = r[1]
        total = int(r[2] or 0)
        null_count = int(r[3] or 0)
        pct = float(r[4] or 0)
        passed = pct <= max_null_rate * 100
        checks.append(QualityCheckResult(
            check_type="null_rate", column=col,
            passed=passed,
            detail=f"空值 {null_count}/{total} ({pct:.1f}%)",
            actual_value=f"{pct:.1f}%",
            expected_value=f"≤ {max_null_rate:.0%}",
        ))
    for col in col_names:
        if col not in checked_null:
            checks.append(QualityCheckResult(
                check_type="null_rate", column=col,
                passed=True,
                detail="空值率 0%",
                actual_value="0%", expected_value=f"≤ {max_null_rate:.0%}",
            ))

    # ── 字段超长 ──
    length_rows = results.get("field_length", [])
    by_len_col: dict[str, list] = {}
    for r in length_rows:
        by_len_col.setdefault(r[1], []).append(r)
    for ci in column_infos:
        max_len = _parse_max_length(ci.data_type)
        if max_len is None:
            continue
        violations = by_len_col.get(ci.name, [])
        if violations:
            preview = ", ".join(f"len={v[2]}" for v in violations[:3])
            if len(violations) > 3:
                preview += f" (及其他 {len(violations) - 3} 处)"
            checks.append(QualityCheckResult(
                check_type="field_length", column=ci.name,
                passed=False,
                detail=f"{len(violations)} 行超过最大长度 {max_len}",
                actual_value=preview,
                expected_value=f"≤ {max_len} 字符",
            ))
        else:
            checks.append(QualityCheckResult(
                check_type="field_length", column=ci.name,
                passed=True,
                detail=f"所有值 ≤ {max_len} 字符",
                actual_value="0 超长",
                expected_value=f"≤ {max_len} 字符",
            ))

    # ── 码值合规 ──
    code_rows = results.get("code_compliance", [])
    by_code_col: dict[str, list] = {}
    for r in code_rows:
        by_code_col.setdefault(r[1], []).append(r)
    for ci in column_infos:
        if not ci.code_values:
            continue
        violations = by_code_col.get(ci.name, [])
        if violations:
            parts = [f"'{v[2]}': {v[3]}行" for v in violations[:5]]
            codes = sorted(c.value for c in ci.code_values)
            checks.append(QualityCheckResult(
                check_type="code_compliance", column=ci.name,
                passed=False,
                detail=f"发现 {len(violations)} 个非法码值",
                actual_value=", ".join(parts),
                expected_value=f"合法码值: {codes}",
            ))
        else:
            codes = sorted(c.value for c in ci.code_values)
            checks.append(QualityCheckResult(
                check_type="code_compliance", column=ci.name,
                passed=True,
                detail="全部码值合规",
                actual_value=f"合法码值 {len(codes)} 个",
                expected_value=f"合法码值: {codes}",
            ))

    return QualityReport(
        total_rows=expected_row_count,
        total_columns=len(col_names),
        checks=checks,
    )


# ============================================================================
# 笛卡尔积检测（元数据检查 — Python）
# ============================================================================

def check_cartesian_product(
    actual_rows: int,
    source_table_counts: dict[str, int],
    join_pairs: list[tuple[str, str]] | None = None,
    max_bloat_ratio: float = 5.0,
) -> QualityCheckResult:
    if not source_table_counts:
        return QualityCheckResult(check_type="cartesian_product", passed=True, detail="未提供源表行数，跳过")
    if actual_rows == 0:
        return QualityCheckResult(check_type="cartesian_product", passed=True, detail="结果集为空，跳过")

    counts = list(source_table_counts.values())
    max_source = max(counts)

    items = list(source_table_counts.items())
    for r in range(len(items), 1, -1):
        for combo in itertools.combinations(items, r):
            if prod(count for _, count in combo) == actual_rows:
                desc = " × ".join(f"{n}({c})" for n, c in combo)
                return QualityCheckResult(
                    check_type="cartesian_product", passed=False,
                    detail=f"检测到精确笛卡尔积: {desc} = {actual_rows} 行",
                    actual_value=f"实际 {actual_rows} 行 = {desc}",
                    expected_value=f"≤ {max_source}",
                )

    ratio = actual_rows / max_source if max_source > 0 else float("inf")
    if ratio > max_bloat_ratio:
        return QualityCheckResult(
            check_type="cartesian_product", passed=False,
            detail=f"结果行数 ({actual_rows}) 是最大源表 ({max_source}) 的 {ratio:.1f}x，疑似 JOIN 缺失",
            actual_value=f"膨胀比 {ratio:.1f}x",
            expected_value=f"≤ {max_bloat_ratio}x",
        )

    if join_pairs:
        joined = set()
        for l, r in join_pairs:
            joined.add(l); joined.add(r)
        isolated = set(source_table_counts.keys()) - joined
        if isolated:
            return QualityCheckResult(
                check_type="cartesian_product", passed=False,
                detail=f"表 {sorted(isolated)} 缺少 JOIN 条件",
                actual_value=f"孤立表: {isolated}",
                expected_value="所有表应有关联条件",
            )

    return QualityCheckResult(
        check_type="cartesian_product", passed=True,
        detail=f"行数 {actual_rows} 在合理范围内",
        actual_value=f"膨胀比 {ratio:.1f}x",
        expected_value=f"≤ {max_bloat_ratio}x",
    )


# ============================================================================
# 一键执行
# ============================================================================

def run_quality_tests(
    conn,
    original_sql: str,
    column_infos: list[ColumnInfo],
    pk_columns: list[str] | None = None,
    max_null_rate: float = 0.10,
    check_code_values: bool = True,
    source_table_counts: dict[str, int] | None = None,
    join_pairs: list[tuple[str, str]] | None = None,
) -> QualityReport:
    """一键执行 L1 质量检查 (generate → execute → parse)"""
    # 行数
    try:
        cur = conn.execute(generate_row_count_sql(original_sql))
        total = cur.fetchone()[0]
    except Exception:
        total = 0

    # 检查 SQL
    test_sql = generate_all_checks_sql(original_sql, column_infos, pk_columns, check_code_values)
    try:
        cur = conn.execute(test_sql)
        rows = cur.fetchall()
    except Exception as e:
        return QualityReport(
            total_rows=0, total_columns=len(column_infos),
            checks=[QualityCheckResult(check_type="execution_error", passed=False,
                      detail=f"测试 SQL 执行失败: {e}")],
        )

    report = parse_test_results(rows, column_infos, pk_columns, max_null_rate, total)
    report.total_rows = total

    if source_table_counts:
        report.checks.append(check_cartesian_product(total, source_table_counts, join_pairs))

    return report


# ============================================================================
# 内部工具
# ============================================================================

def _parse_max_length(data_type: str) -> Optional[int]:
    if not data_type:
        return None
    dt = data_type.lower().strip()
    if not any(dt.startswith(t) for t in ("varchar", "char", "nvarchar", "nchar")):
        return None
    m = re.search(r"\((\d+)\)", dt)
    if m:
        return int(m.group(1))
    if dt == "char":
        return 1
    return None


def _group(rows: list[tuple]) -> dict[str, list[tuple]]:
    g: dict[str, list[tuple]] = {}
    for r in rows:
        g.setdefault(r[0] if r else "", []).append(r)
    return g
