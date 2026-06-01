"""
L1 数据质量检查 — SQL 生成（纯函数，无副作用）

从 testing/quality.py 拆分，SRP: SQL 片段生成独立于执行/解析层。

设计原则：
  原始 SQL 被包成 CTE (_source)，检查逻辑写成 SELECT 语句在数据库内执行。
  数据库只返回违规行，不做大规模数据传输。

  错误做法: SQL → Python load 1000万行 → for row in rows: check → O(n) 内存爆炸
  正确做法: SQL → WRAP AS CTE → test SQL → DB 执行 → 只返回 3 行违规 → O(1)

所有检查子查询统一为 5 列 schema:
  (check_type, column_name, value1, value2, value3)
保证 UNION ALL 可行，parse_test_results 按 check_type 分派解析。

使用方式：
    # 新（推荐）: 直接导入
    from testing.quality_sql import generate_all_checks_sql

    # 旧（兼容）: 通过 quality.py 重导出
    from testing.quality import generate_all_checks_sql  # 仍然有效
"""
import re
from typing import Optional

from models import ColumnInfo

# ============================================================================
# 常量
# ============================================================================

CTE_NAME = "_source"

# 统一列 schema 的列别名
C1, C2, C3, C4, C5 = "check_type", "column_name", "v1", "v2", "v3"


# ============================================================================
# CTE 包装
# ============================================================================

def _cte(original_sql: str) -> str:
    """生成顶层 CTE 包装"""
    sql = original_sql.rstrip().rstrip(";").rstrip()
    return f"WITH {CTE_NAME} AS (\n{sql}\n)"


wrap_as_cte = _cte  # 对外别名


# ============================================================================
# 单检查 SQL 生成（对外，含 CTE 包装）
# ============================================================================

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


def generate_pk_uniqueness_sql(original_sql: str, pk_columns: list[str]) -> str:
    """生成主键唯一性检查 SQL（含 CTE 包装）"""
    if not pk_columns:
        return ""
    return _cte(original_sql) + "\n" + _pk_sql(pk_columns)


# ============================================================================
# 内部：不含 CTE 的 SQL 片段（给 generate_all_checks_sql 复用单 CTE）
# ============================================================================

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
# 内部工具
# ============================================================================

def _parse_max_length(data_type: str) -> Optional[int]:
    """从数据类型字符串中解析最大长度 (varchar(32) → 32)"""
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
