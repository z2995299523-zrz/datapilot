"""
数仓建模编排引擎 — 全链路一键建模入口

Pipeline:
  classify → assign_layers → detect_relations → detect_codes
  → classify_schema → build_schemas → validate_quality
"""

from models import (TableInfo, DataLayer, ModelingResult, ModelingRequest,
                    TableRole, TableClassification)
from modeling.classifier import classify_all
from modeling.layer_assigner import assign_layer
from modeling.relation_detector import detect_relationships
from modeling.code_detector import detect_code_columns
from modeling.schema_classifier import classify_schema
from modeling.schema_builder import build_schemas
from modeling.quality_validator import validate_quality


class ModelingEngine:
    """数仓建模引擎 — 编排全链路"""

    def __init__(self, llm_enabled: bool = True):
        self.llm_enabled = llm_enabled

    def analyze(self, req: ModelingRequest) -> ModelingResult:
        """一键全链路建模

        Args:
            req: ModelingRequest (tables, source_name, flags)

        Returns:
            ModelingResult with complete modeling output
        """
        tables = req.tables
        if not tables:
            return ModelingResult(
                source_name=req.source_name,
                total_tables=0,
            )

        # Step 1: Classify all tables
        classifications = classify_all(tables, llm_enabled=req.enable_llm)

        # Step 2: Assign layers
        layers: dict[str, list[str]] = {}
        for t in tables:
            cls = classifications.get(t.table_name)
            layer = assign_layer(t, cls) if cls else DataLayer.DWS
            layer_name = layer.value
            layers.setdefault(layer_name, []).append(t.table_name)
            if cls:
                cls.layer = layer

        # Step 3: Detect FK-PK relationships
        relationships = detect_relationships(tables, llm_enabled=req.enable_llm)

        # Step 4: Detect code columns
        code_columns = detect_code_columns(tables) if req.detect_codes else []

        # Step 5: Classify schema type (use all tables as one schema for classification)
        schema_def = classify_schema(tables, relationships, classifications, name=req.source_name or "main")
        schemas = build_schemas(tables, classifications, relationships, schema_def.schema_type)

        # Step 6: Validate quality
        quality_issues = validate_quality(layers, tables, classifications, relationships, schemas) \
            if req.validate_quality else []

        return ModelingResult(
            source_name=req.source_name,
            layers=layers,
            classifications=classifications,
            relationships=relationships,
            code_columns=code_columns,
            schemas=schemas,
            quality_issues=quality_issues,
            total_tables=len(tables),
            llm_used=req.enable_llm,
        )


# Module-level convenience
def run_modeling(req: ModelingRequest) -> ModelingResult:
    """快速一键建模"""
    engine = ModelingEngine(llm_enabled=req.enable_llm)
    return engine.analyze(req)
