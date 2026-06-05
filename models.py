"""
DataPilot 核心数据模型

所有 LLM 输出和模块间传递的数据都用 Pydantic 强校验
"""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# ============================================================================
# 数据字典模型
# ============================================================================

class DataLayer(str, Enum):
    """数据分层 — 检索优先级从高到低"""
    DM = "DM"    # 数据集市层，最接近业务
    ADS = "ADS"  # 应用数据服务层 — 面向具体应用场景的聚合视图
    DWS = "DWS"  # 数据服务层
    ODS = "ODS"  # 原始数据层


class CodeMapping(BaseModel):
    """码值映射: cust_status → {01: 活跃, 02: 休眠, 03: 销户}"""
    value: str
    meaning: str


class ColumnInfo(BaseModel):
    """字段信息"""
    name: str = Field(..., description="字段名")
    data_type: str = Field(default="", description="类型，如 varchar(2)")
    comment: str = Field(default="", description="字段注释")
    code_values: list[CodeMapping] = Field(default_factory=list, description="码值映射")
    is_primary_key: bool = Field(default=False)
    is_foreign_key: bool = Field(default=False)
    referenced_table: Optional[str] = Field(default=None, description="外键引用表")


class TableInfo(BaseModel):
    """表信息"""
    table_name: str = Field(..., description="表名")
    table_comment: str = Field(default="", description="表注释")
    layer: DataLayer = Field(..., description="数据分层")
    schema_name: str = Field(default="", description="数据库/schema 名")
    columns: list[ColumnInfo] = Field(default_factory=list)
    source_file: str = Field(default="", description="来源文件")


class DataDictionary(BaseModel):
    """完整数据字典"""
    tables: list[TableInfo] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict, description="字典元信息")


# ============================================================================
# 业务概念模型
# ============================================================================

class ConceptType(str, Enum):
    ENTITY = "entity"           # 实体: 客户, 产品
    DIMENSION = "dimension"     # 维度: 渠道, 地区
    TIME_RANGE = "time_range"   # 时间范围: 近6个月
    METRIC = "metric"           # 度量: 交易金额, 客户数
    CONDITION = "condition"     # 条件: 正常情况下, 有效


class BusinessConcept(BaseModel):
    """从需求文档中提取的业务概念"""
    concept: str = Field(..., description="业务概念")
    context: str = Field(default="", description="在需求中的上下文")
    type: ConceptType = Field(default=ConceptType.ENTITY)
    candidates: list[str] = Field(default_factory=list, description="同义词/近义词，提高检索命中率")
    qualifier: str = Field(default="", description="限定条件，如 'cust_status=01'")


class ConceptExtractionResult(BaseModel):
    """概念提取结果"""
    concepts: list[BusinessConcept] = Field(default_factory=list)
    raw_requirement: str = Field(default="")
    llm_error: str = Field(default="", description="LLM 调用失败时的错误信息")
    llm_token_usage: dict = Field(default_factory=dict, description="Token 使用统计")


# ============================================================================
# 检索匹配模型
# ============================================================================

class ColumnMatch(BaseModel):
    """匹配到的字段"""
    name: str
    comment: str
    data_type: str = ""
    code_values: list[CodeMapping] = Field(default_factory=list)


class TableMatch(BaseModel):
    """单个概念的匹配结果"""
    concept: str
    matched: bool = False
    layer: Optional[DataLayer] = None
    table_name: Optional[str] = None
    table_comment: Optional[str] = None
    columns: list[ColumnMatch] = Field(default_factory=list)
    score: float = 0.0
    message: str = ""  # 未匹配时的提示


class RetrievalResult(BaseModel):
    """检索结果（所有概念的匹配汇总）"""
    matches: list[TableMatch] = Field(default_factory=list)
    unmatched_concepts: list[str] = Field(default_factory=list)
    retrieval_log: list[str] = Field(default_factory=list)  # 每层检索日志


# ============================================================================
# 伪代码模型
# ============================================================================

class PseudoCodeStep(BaseModel):
    """伪代码步骤"""
    step_number: int
    description: str
    source_table: str = ""
    conditions: list[str] = Field(default_factory=list)
    joins: list[str] = Field(default_factory=list)
    aggregations: list[str] = Field(default_factory=list)
    output: str = ""


class PseudoCode(BaseModel):
    """伪代码"""
    title: str = ""
    steps: list[PseudoCodeStep] = Field(default_factory=list)
    todo_items: list[str] = Field(default_factory=list)  # 未确认的部分
    notes: list[str] = Field(default_factory=list)        # 备注


# ============================================================================
# 分析报告（顶层输出）
# ============================================================================

class AnalysisReport(BaseModel):
    """需求分析报告"""
    requirement_text: str = ""
    concepts: list[BusinessConcept] = Field(default_factory=list)
    retrieval: RetrievalResult = Field(default_factory=RetrievalResult)
    pseudocode: Optional[PseudoCode] = None


# ============================================================================
# 断言模型 — 业务概念 → SQL 条件翻译
# ============================================================================

class AssertionType(str, Enum):
    CODE = "code"              # 码值条件: cust_status = '01'
    TIME = "time"              # 时间条件: trans_date >= '2025-01-01'
    AGG = "aggregation"        # 聚合条件: SUM(txn_amt)


class Assertion(BaseModel):
    """业务概念到 SQL 条件的确定性格言"""
    type: AssertionType
    column: str = ""
    operator: str = "="                    # SQL operator: =, >=, <=, IN, BETWEEN
    value: str = ""                         # Literal value or SQL expression
    concept_source: str = ""                # Source concept name
    table: str = ""                         # Target table
    confidence: float = 0.0                 # Match confidence 0-1
    sql_condition: str = ""                 # Pre-compiled SQL WHERE clause


# ============================================================================
# 预期结果比对模型 (L2.5)
# ============================================================================

class ValueDiff(BaseModel):
    """逐行逐列的数值差异"""
    key_values: str = ""                     # 对齐键值，如 "分行3"
    column: str = ""                          # 差异列名
    expected_value: str = ""                  # 预期值
    actual_value: str = ""                    # 实际值
    diff_percent: float = 0.0                 # 偏差百分比


class ExpectedComparisonReport(BaseModel):
    """预期结果比对报告"""
    total_expected: int = 0
    total_actual: int = 0
    match_count: int = 0
    mismatch_count: int = 0
    missing_in_actual: list[str] = Field(default_factory=list)  # 预期有、实际无
    extra_in_actual: list[str] = Field(default_factory=list)    # 实际有、预期无
    value_diffs: list[ValueDiff] = Field(default_factory=list)   # 数值偏差
    overall_passed: bool = True
    summary: str = ""


# ============================================================================
# LLM 诊断响应模型（L3 → LLM 输出校验）
# ============================================================================

class DiagnosisRule(BaseModel):
    """单条诊断规则 — DIAGNOSIS_RULES 的类型化替代"""
    check_type: str
    severity: str = "medium"
    symptom: str = ""
    root_cause: str = ""
    fix: str = ""
    prevention: str = ""
    auto_fixable: bool = False
    fix_level: str = ""  # "syntax" | "semantic" | ""


class LLMDiagnosisItem(BaseModel):
    """LLM 返回的单条诊断"""
    severity: str = "medium"
    source: str = ""
    symptom: str = ""
    root_cause: str = ""
    impact: str = ""
    fix_suggestion: str = ""
    prevention: str = ""
    affected_columns: list[str] = Field(default_factory=list)
    is_auto_fixable: bool = False


class LLMDiagnosisResponse(BaseModel):
    """LLM 诊断响应 — Pydantic 强校验"""
    items: list[LLMDiagnosisItem] = Field(default_factory=list)


# ============================================================================
# LLM 测试代码生成响应模型
# ============================================================================

class LLMTestCase(BaseModel):
    """LLM 生成的单条测试"""
    check_type: str = Field(..., description="检查类型: pk_uniqueness/null_rate/field_length/code_compliance/business_rule/aggregation/boundary")
    column_name: str = Field(default="", description="检查的列名")
    description: str = Field(default="", description="这条测试在检查什么")
    test_sql: str = Field(..., description="可执行的测试 SQL（只返回违规行）")
    expected_behavior: str = Field(default="", description="通过条件")


class LLMTestSuiteResponse(BaseModel):
    """LLM 生成的完整测试套件"""
    suite_description: str = Field(default="", description="测试套件概述")
    test_cases: list[LLMTestCase] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, description="补充说明")


# ============================================================================
# 数仓建模引擎模型 (DW Modeling Engine)
# ============================================================================

class TableRole(str, Enum):
    """表在数仓模型中的角色"""
    FACT = "fact"               # 事实表：度量值 + 指向维度的外键
    DIMENSION = "dimension"     # 维表：描述性属性，参照表
    BRIDGE = "bridge"           # 桥接表：解决 M:N 关系，仅含外键
    AGGREGATE = "aggregate"     # 汇总表：预聚合结果
    UNKNOWN = "unknown"         # 无法分类


class SchemaType(str, Enum):
    """数仓建模模式类型"""
    STAR = "star"               # 星型模型：中心事实表 + 直接维表
    SNOWFLAKE = "snowflake"     # 雪花模型：维表进一步规范化
    THREEF_NF = "3nf"           # 三范式：完全规范化
    UNKNOWN = "unknown"


class RelationshipType(str, Enum):
    """表关系基数"""
    ONE_TO_MANY = "1:N"
    MANY_TO_ONE = "N:1"
    MANY_TO_MANY = "M:N"


class QualitySeverity(str, Enum):
    """质量问题严重度"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ConsistencyRule(str, Enum):
    """口径一致性规则"""
    SAME_NAME_SAME_MEANING = "same_name_same_meaning"
    SAME_FIELD_SAME_CALIBER = "same_field_same_caliber"
    PK_TYPE_MATCHES_FK_TYPE = "pk_type_matches_fk_type"
    CODE_CONSISTENCY = "code_consistency"
    DIMENSION_CONFORMITY = "dimension_conformity"
    CROSS_LAYER_CONSISTENCY = "cross_layer_consistency"


class TableRelationship(BaseModel):
    """两张表之间的外键关系"""
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    relationship_type: RelationshipType = RelationshipType.MANY_TO_ONE
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    detection_method: str = ""  # "explicit_fk" | "name_match" | "semantic_match" | "type_match" | "llm"


class CodeCandidate(BaseModel):
    """检测到的候选码值列"""
    column_name: str
    table_name: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    detection_reason: str = ""
    candidate_values: list[CodeMapping] = Field(default_factory=list)


class TableClassification(BaseModel):
    """单表的角色 + 分层分类结果"""
    table_name: str
    role: TableRole = TableRole.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    layer: Optional[DataLayer] = None
    score_detail: dict = Field(default_factory=dict)  # {FACT: 2.5, DIMENSION: 1.0, ...}


class QualityIssue(BaseModel):
    """口径一致性校验发现的问题"""
    rule: ConsistencyRule
    severity: QualitySeverity = QualitySeverity.WARNING
    table: str = ""
    column: str = ""
    description: str = ""
    suggestion: str = ""


class SchemaDefinition(BaseModel):
    """一个完整的数仓模式（星型/雪花/3NF）"""
    name: str
    schema_type: SchemaType = SchemaType.UNKNOWN
    tables: list[str] = Field(default_factory=list)  # table names
    relationships: list[TableRelationship] = Field(default_factory=list)
    description: str = ""


class ModelingResult(BaseModel):
    """数仓建模引擎的完整输出"""
    source_name: str = ""
    layers: dict[str, list[str]] = Field(default_factory=dict)  # {layer: [table_names]}
    classifications: dict[str, TableClassification] = Field(default_factory=dict)  # {table_name: ...}
    relationships: list[TableRelationship] = Field(default_factory=list)
    code_columns: list[CodeCandidate] = Field(default_factory=list)
    schemas: list[SchemaDefinition] = Field(default_factory=list)
    quality_issues: list[QualityIssue] = Field(default_factory=list)
    total_tables: int = 0
    llm_used: bool = False
    metadata: dict = Field(default_factory=dict)


class ModelingRequest(BaseModel):
    """数仓建模请求"""
    source_name: str = ""
    tables: list[TableInfo] = Field(default_factory=list)
    enable_llm: bool = True
    detect_codes: bool = True
    validate_quality: bool = True


class EvolveRequest(BaseModel):
    """模型演进请求 — 新增源表合并到已有模型"""
    existing_model: ModelingResult = Field(default_factory=ModelingResult)
    new_tables: list[TableInfo] = Field(default_factory=list)
    merge_strategy: str = "auto"  # "auto" | "create_new" | "merge"
    enable_llm: bool = True
