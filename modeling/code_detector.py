"""
码值列检测器 — 识别哪些列是码值/枚举列

三重检测: 列名关键词 + 数据类型长度 + 注释提示
"""

import re
from models import TableInfo, ColumnInfo, CodeCandidate, CodeMapping


CODE_NAME_KEYWORDS = [
    "type", "status", "code", "category", "flag", "class", "state", "level",
    "级别", "类型", "状态", "代码", "类别", "标志", "种类", "等级",
    "gender", "sex", "grade", "region", "channel",
]

CODE_LIKE_TYPES = ["char", "varchar", "nvarchar", "text"]


def _looks_like_code_col(col: ColumnInfo) -> tuple[bool, float, str]:
    """启发式检测一个列是否像码值列

    Returns: (is_code, weight, reason)
    """
    name_lower = col.name.lower()

    # Already has code values parsed
    if len(col.code_values) > 0:
        return True, 1.0, "pre-parsed code values"

    weight = 0.0
    reasons: list[str] = []

    # Name match
    for kw in CODE_NAME_KEYWORDS:
        if kw in name_lower:
            weight += 0.3
            reasons.append(f"name keyword '{kw}'")
            break

    # Type + length heuristics
    type_lower = col.data_type.lower()
    if any(t in type_lower for t in CODE_LIKE_TYPES):
        match = re.search(r"\((\d+)\)", col.data_type)
        if match:
            length = int(match.group(1))
            if length <= 3:
                weight += 0.5
                reasons.append(f"very short varchar({length})")
            elif length <= 10:
                weight += 0.3
                reasons.append(f"short varchar({length})")
        else:
            weight += 0.1
            reasons.append("string type")

    # Comment hints
    if col.comment:
        for hint in ["码值", "代码", "类型", "状态", "枚举", "code", "type", "status"]:
            if hint in col.comment.lower():
                weight += 0.2
                reasons.append(f"comment hint '{hint}'")
                break

    # Exclude: PK is not a code column
    if col.is_primary_key:
        weight -= 0.5
        reasons.append("primary key exclusion")

    return weight > 0.3, min(weight, 1.0), "; ".join(reasons)


def _extract_codes_from_comment(comment: str) -> list[CodeMapping]:
    """从注释中提取码值，支持格式: '01=active,02=inactive' 或 '1:男,2:女'"""
    if not comment:
        return []
    results: list[CodeMapping] = []
    # Match patterns like 01=active, 1:男, 01-已激活
    pairs = re.findall(r"(\d+[=:\-][^\s,;，；]+)", comment)
    for pair in pairs[:10]:
        for sep in ["=", ":", "-"]:
            if sep in pair:
                parts = pair.split(sep, 1)
                if len(parts) == 2:
                    results.append(CodeMapping(value=parts[0].strip(), meaning=parts[1].strip()))
                break
    return results


def detect_code_columns(tables: list[TableInfo]) -> list[CodeCandidate]:
    """检测所有表中的候选码值列"""
    candidates: list[CodeCandidate] = []

    for ti in tables:
        for col in ti.columns:
            is_code, confidence, reason = _looks_like_code_col(col)
            if is_code:
                candidates.append(CodeCandidate(
                    column_name=col.name,
                    table_name=ti.table_name,
                    confidence=round(confidence, 3),
                    detection_reason=reason,
                    candidate_values=col.code_values if col.code_values
                    else _extract_codes_from_comment(col.comment),
                ))

    return candidates
