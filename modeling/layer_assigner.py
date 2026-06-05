"""
分层分配器 — 将表分配到 ODS / DWS / ADS / DM 层

使用 4 规则加权评分系统。
"""

from models import TableInfo, DataLayer, TableRole, TableClassification


# ── 命名模式 ──
ODS_NAME_PATTERNS = ["ods_", "raw_", "stg_", "staging", "src_", "ingest"]
DWS_NAME_PATTERNS = ["dws_", "dw_", "fact_", "dim_"]
ADS_NAME_PATTERNS = ["ads_", "app_", "agg_", "rpt_", "report"]
DM_NAME_PATTERNS = ["v_", "view_", "dm_", "mart"]


def _has_numeric(col) -> bool:
    t = col.data_type.lower()
    return any(nt in t for nt in ("int", "decimal", "numeric", "float", "double", "number"))


def assign_layer(ti: TableInfo, classification: TableClassification) -> DataLayer:
    """为一张表分配数仓分层

    得分制：{ODS: s1, DWS: s2, ADS: s3, DM: s4}，取最高分。
    """
    scores: dict[DataLayer, float] = {
        DataLayer.ODS: 0.0,
        DataLayer.DWS: 0.0,
        DataLayer.ADS: 0.0,
        DataLayer.DM: 0.0,
    }
    name_lower = ti.table_name.lower()
    role = classification.role
    has_code = any(len(c.code_values) > 0 for c in ti.columns)
    has_measures = any(_has_numeric(c) for c in ti.columns)

    # ── Rule 1: Already has a layer (from input) ──
    try:
        if ti.layer:
            scores[ti.layer] += 5.0
    except ValueError:
        pass

    # ── Rule 2: Role-based default ──
    if role == TableRole.DIMENSION:
        scores[DataLayer.ODS] += 1.0
        scores[DataLayer.DWS] += 1.0
    elif role == TableRole.FACT:
        scores[DataLayer.DWS] += 2.0
    elif role == TableRole.BRIDGE:
        scores[DataLayer.DWS] += 2.0
    elif role == TableRole.AGGREGATE:
        scores[DataLayer.ADS] += 2.0
        scores[DataLayer.DM] += 1.0

    # ── Rule 3: Naming heuristics ──
    if any(kw in name_lower for kw in ODS_NAME_PATTERNS):
        scores[DataLayer.ODS] += 2.0
    if any(kw in name_lower for kw in DWS_NAME_PATTERNS):
        scores[DataLayer.DWS] += 2.0
    if any(kw in name_lower for kw in ADS_NAME_PATTERNS):
        scores[DataLayer.ADS] += 2.0
    if any(kw in name_lower for kw in DM_NAME_PATTERNS):
        scores[DataLayer.DM] += 2.0

    # ── Rule 4: Structure-based ──
    if has_code and not has_measures:
        scores[DataLayer.DWS] += 1.0
    if has_measures and len(ti.columns) >= 10:
        scores[DataLayer.DWS] += 1.0
    if has_measures and len(ti.columns) <= 8 and role == TableRole.AGGREGATE:
        scores[DataLayer.ADS] += 1.0
    if ti.table_comment and any(
        kw in ti.table_comment for kw in ("报表", "报告", "dashboard", "看板", "展示")
    ):
        scores[DataLayer.DM] += 2.0

    # ── Pick winner ──
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return DataLayer.DWS  # default fallback
    return best
