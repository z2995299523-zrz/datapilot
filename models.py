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
# LLM 诊断响应模型（L3 → LLM 输出校验）
# ============================================================================

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
