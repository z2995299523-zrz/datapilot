"""
结果排序 + 去重
"""
from models import TableMatch


def rank_matches(
    matches: list[TableMatch],
    dedup_key: callable = None,
) -> list[TableMatch]:
    """对匹配结果去重并按分数降序排列

    Args:
        matches: 待处理的匹配列表
        dedup_key: 去重函数，默认按 (concept, table_name) 去重，保留高分

    Returns:
        排序后的匹配列表
    """
    if not matches:
        return []

    if dedup_key is None:
        dedup_key = lambda m: (m.concept, m.table_name)

    seen: dict[tuple, TableMatch] = {}
    for m in matches:
        key = dedup_key(m)
        if key not in seen or m.score > seen[key].score:
            seen[key] = m

    result = list(seen.values())
    result.sort(key=lambda m: m.score, reverse=True)
    return result


def merge_table_matches(
    existing: TableMatch,
    incoming: TableMatch,
) -> TableMatch:
    """合并两个命中同一表的匹配结果（不同概念 → 同一表）"""
    existing.columns = _merge_columns(existing.columns, incoming.columns)
    # 取更高分
    if incoming.score > existing.score:
        existing.score = incoming.score
    return existing


def _merge_columns(
    cols_a: list,
    cols_b: list,
) -> list:
    """合并字段列表，按 name 去重，保留首次出现的"""
    seen = set()
    merged = []
    for col in cols_a + cols_b:
        if col.name not in seen:
            seen.add(col.name)
            merged.append(col)
    return merged
