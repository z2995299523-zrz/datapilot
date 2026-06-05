"""
口径一致性校验器 — 跨层检查字段命名、类型、码值等一致性

4 条核心规则:
  1. 同名同义: 同名字段跨层类型一致
  2. 码值一致: 码值集跨层相同
  3. PK-FK 类型匹配: FK 类型 == PK 类型
  4. 维表一致性: 同维表跨 schema 结构相同
"""

from collections import defaultdict

from models import (TableInfo, DataLayer, TableRelationship, TableClassification,
                    TableRole, SchemaDefinition, ConsistencyRule, QualitySeverity, QualityIssue)


def validate_quality(
    layers: dict[str, list[str]],
    tables: list[TableInfo],
    classifications: dict[str, TableClassification],
    relationships: list[TableRelationship],
    schemas: list[SchemaDefinition],
) -> list[QualityIssue]:
    """运行全部口径一致性校验规则"""
    issues: list[QualityIssue] = []
    table_map = {t.table_name: t for t in tables}

    issues.extend(_check_same_name_same_meaning(tables))
    issues.extend(_check_code_consistency(tables))
    issues.extend(_check_pk_fk_type_match(relationships, table_map))
    issues.extend(_check_dimension_conformity(schemas, classifications, table_map))

    return issues


def _check_same_name_same_meaning(tables: list[TableInfo]) -> list[QualityIssue]:
    """Rule 1: 同名字段跨层类型必须一致"""
    issues: list[QualityIssue] = []
    col_map: dict[str, list[tuple[str, DataLayer, str]]] = defaultdict(list)

    for t in tables:
        for col in t.columns:
            col_map[col.name.lower()].append((t.table_name, t.layer, col.data_type))

    for col_name, occurrences in col_map.items():
        if len(occurrences) < 2:
            continue
        types = set(o[2] for o in occurrences if o[2])
        if len(types) > 1:
            layers_involved = set(o[1].value for o in occurrences if o[1])
            issues.append(QualityIssue(
                rule=ConsistencyRule.SAME_NAME_SAME_MEANING,
                severity=QualitySeverity.WARNING,
                column=col_name,
                description=f"Column '{col_name}' has inconsistent types across layers "
                            f"{layers_involved}: {types}",
                suggestion="Standardize data type across all layers",
            ))

    return issues


def _check_code_consistency(tables: list[TableInfo]) -> list[QualityIssue]:
    """Rule 2: 码值集跨层必须一致"""
    issues: list[QualityIssue] = []
    col_map: dict[str, list[tuple[str, DataLayer, set[str]]]] = defaultdict(list)

    for t in tables:
        for col in t.columns:
            if len(col.code_values) > 0:
                codes = {cv.value for cv in col.code_values}
                col_map[col.name.lower()].append((t.table_name, t.layer, codes))

    for col_name, occurrences in col_map.items():
        if len(occurrences) < 2:
            continue
        ref_codes = occurrences[0][2]
        for tbl, layer, codes in occurrences[1:]:
            if codes != ref_codes:
                missing = ref_codes - codes
                extra = codes - ref_codes
                issues.append(QualityIssue(
                    rule=ConsistencyRule.CODE_CONSISTENCY,
                    severity=QualitySeverity.ERROR if missing else QualitySeverity.WARNING,
                    table=tbl,
                    column=col_name,
                    description=f"Code values differ between '{occurrences[0][0]}' and '{tbl}': "
                                f"missing={missing}, extra={extra}",
                    suggestion="Unify code value mappings across layers",
                ))

    return issues


def _check_pk_fk_type_match(relationships: list[TableRelationship],
                            table_map: dict[str, TableInfo]) -> list[QualityIssue]:
    """Rule 3: FK 列类型必须匹配 PK 列类型"""
    issues: list[QualityIssue] = []

    for rel in relationships:
        src = table_map.get(rel.source_table)
        tgt = table_map.get(rel.target_table)
        if not src or not tgt:
            continue
        src_col = next((c for c in src.columns if c.name == rel.source_column), None)
        tgt_col = next((c for c in tgt.columns if c.name == rel.target_column), None)
        if not src_col or not tgt_col:
            continue

        src_type = src_col.data_type.lower().split("(")[0].strip()
        tgt_type = tgt_col.data_type.lower().split("(")[0].strip()

        if src_type and tgt_type and src_type != tgt_type:
            issues.append(QualityIssue(
                rule=ConsistencyRule.PK_TYPE_MATCHES_FK_TYPE,
                severity=QualitySeverity.ERROR,
                table=rel.source_table,
                column=rel.source_column,
                description=f"FK '{rel.source_table}.{rel.source_column}' type ({src_type}) "
                            f"≠ PK '{rel.target_table}.{rel.target_column}' type ({tgt_type})",
                suggestion=f"Align '{rel.source_column}' type to {tgt_type}",
            ))

    return issues


def _check_dimension_conformity(
    schemas: list[SchemaDefinition],
    classifications: dict[str, TableClassification],
    table_map: dict[str, TableInfo],
) -> list[QualityIssue]:
    """Rule 4: 同维表跨 schema 结构必须一致"""
    issues: list[QualityIssue] = []
    dim_schemas: dict[str, list[str]] = defaultdict(list)

    for schema in schemas:
        for tname in schema.tables:
            cls = classifications.get(tname)
            if cls and cls.role == TableRole.DIMENSION:
                dim_schemas[tname].append(schema.name)

    for dim_name, schema_list in dim_schemas.items():
        if len(schema_list) <= 1:
            continue
        # Find tables in different schemas with same dimension name
        dim_tables = [t for t in table_map.values() if t.table_name == dim_name]
        if len(dim_tables) < 2:
            continue
        col_sets = [set(c.name for c in t.columns) for t in dim_tables]
        unique_sets = set(frozenset(cs) for cs in col_sets)
        if len(unique_sets) > 1:
            issues.append(QualityIssue(
                rule=ConsistencyRule.DIMENSION_CONFORMITY,
                severity=QualitySeverity.WARNING,
                table=dim_name,
                description=f"Conformed dimension '{dim_name}' has different column sets "
                            f"across schemas: {schema_list}",
                suggestion="Align dimension columns across all schemas",
            ))

    return issues
