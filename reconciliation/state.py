"""
LangGraph State 定义 — 修复闭环的状态模型

状态在节点间传递，每个节点读取需要的字段、写入新的字段。
LangGraph 的 additive 机制：节点返回 dict 增量合并到 state。
"""
from typing import Optional, TypedDict

from testing.quality import QualityReport
from testing.comparison import ComparisonReport
from testing.diagnosis import DiagnosisReport


class ReconciliationState(TypedDict, total=False):
    """修复闭环全局状态

    LangGraph StateGraph 要求用 TypedDict 或 Pydantic BaseModel。
    这里用 TypedDict，字段均为可选（total=False），每个节点返回需要更新的字段。
    """

    # ── 输入 ──
    requirement_text: str
    original_sql: str
    column_infos_json: str          # ColumnInfo list 序列化为 JSON 字符串
    pk_columns_json: str            # 主键列名 list → JSON

    # ── 报告（节点间传递） ──
    quality_report_json: str        # QualityReport.model_dump_json()
    comparison_report_json: str     # ComparisonReport.model_dump_json()
    diagnosis_report_json: str      # DiagnosisReport.model_dump_json()

    # ── 修复闭环控制 ──
    loop_count: int                 # 当前循环次数
    max_loops: int                  # 最大重试次数（默认 3）
    status: str                     # running / passed / failed / manual_fix_needed
    error_message: str              # 异常信息
    fix_history_json: str           # 修复历史 list[dict] → JSON

    # ── 数据库连接（可选，非序列化） ──
    # conn: 不作为 state 字段传递，由节点自行获取
