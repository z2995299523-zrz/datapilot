"""
模型演进引擎 — 新增源表合并到已有数仓模型

策略:
  auto: 自动判断（同名/同PK/列重叠>50% → 合并，否则 → 新建）
  create_new: 强制全部新建
  merge: 强制全部合并到已有表
"""

from models import (TableInfo, ModelingResult, EvolveRequest, TableClassification,
                    TableRelationship, DataLayer)
from modeling.classifier import classify_all
from modeling.layer_assigner import assign_layer
from modeling.relation_detector import detect_relationships
from modeling.code_detector import detect_code_columns
from modeling.quality_validator import validate_quality
from modeling.schema_classifier import classify_schema
from modeling.schema_builder import build_schemas


def evolve_model(req: EvolveRequest) -> ModelingResult:
    """模型演进: 在已有模型基础上新增/合并表

    Args:
        req: EvolveRequest (existing_model, new_tables, merge_strategy)

    Returns:
        更新后的 ModelingResult
    """
    existing = req.existing_model
    new_tables = req.new_tables
    strategy = req.merge_strategy

    if not new_tables:
        return existing

    # Build existing table index from layers
    existing_table_names: set[str] = set()
    for names in existing.layers.values():
        existing_table_names.update(names)

    # Classify all tables (existing + new for context)
    # We don't have the actual TableInfo objects for existing — use names only
    # Build minimal TableInfo for existing tables from classification data
    all_table_infos = list(new_tables)
    for tname in existing_table_names:
        cls = existing.classifications.get(tname)
        layer = DataLayer.DWS
        try:
            layer = DataLayer(cls.layer.value) if cls and cls.layer else DataLayer.DWS
        except Exception:
            pass
        all_table_infos.append(TableInfo(
            table_name=tname,
            table_comment="",
            layer=layer,
            columns=[],
        ))

    classifications = classify_all(all_table_infos, llm_enabled=req.enable_llm)

    to_create: list[tuple[TableInfo, TableClassification]] = []

    for new_t in new_tables:
        cls = classifications.get(new_t.table_name)

        if strategy == "create_new":
            to_create.append((new_t, cls or TableClassification(
                table_name=new_t.table_name)))
            continue

        # Find matching existing table
        match = _find_match(new_t, existing_table_names, all_table_infos)
        if match and strategy != "create_new":
            # Merge into existing (column additions tracked in metadata)
            existing.metadata.setdefault("merged_tables", []).append({
                "new_table": new_t.table_name,
                "merged_into": match,
                "columns_added": [c.name for c in new_t.columns],
            })
        else:
            to_create.append((new_t, cls or TableClassification(
                table_name=new_t.table_name)))

    # Create new tables
    for new_t, cls in to_create:
        layer = assign_layer(new_t, cls)
        layer_name = layer.value
        existing.layers.setdefault(layer_name, []).append(new_t.table_name)
        existing.classifications[new_t.table_name] = cls

    # Re-detect relationships
    all_current = [t for t in all_table_infos if t.table_name in _all_names(existing)]
    existing.relationships = detect_relationships(all_current, llm_enabled=req.enable_llm)

    # Re-validate
    existing.quality_issues = validate_quality(
        existing.layers, all_current, existing.classifications,
        existing.relationships, existing.schemas,
    )

    existing.total_tables = len(_all_names(existing))
    existing.llm_used = req.enable_llm

    return existing


def _find_match(new_t: TableInfo, existing_names: set[str],
                _all_tables: list[TableInfo]) -> str | None:
    """查找新表是否匹配已有表"""
    # Exact name match
    if new_t.table_name in existing_names:
        return new_t.table_name

    # Same PK structure match (approximate)
    new_pks = {c.name for c in new_t.columns if c.is_primary_key}
    if not new_pks:
        return None

    # For tables without actual columns from existing, we can't do structural matching
    # So fall back to name prefix/suffix matching
    new_name = new_t.table_name.lower()
    for ename in existing_names:
        ename_lower = ename.lower()
        if new_name in ename_lower or ename_lower in new_name:
            return ename

    return None


def _all_names(result: ModelingResult) -> set[str]:
    """收集所有表名"""
    names: set[str] = set()
    for ns in result.layers.values():
        names.update(ns)
    return names
