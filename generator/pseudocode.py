"""
伪代码生成器

架构: LangChain PromptTemplate（prompt 管理）+ chat_json（自带 3 次 retry）+ PydanticOutputParser（schema 校验）

与概念提取器一致：Prompt 由 LangChain 集中管理，LLM 调用走 chat_json 保证容错，
结果解析走 PydanticOutputParser 保证 schema 校验。
"""
import json
from langchain_core.output_parsers import PydanticOutputParser

from models import (
    PseudoCode, PseudoCodeStep, RetrievalResult, BusinessConcept,
)
from extractor.prompts import build_pseudocode_prompt
from llm_client import chat_json
from callbacks.token_tracker import TokenTracker


def _format_matches(retrieval: RetrievalResult) -> str:
    """将检索结果格式化为 LLM 可读的 Markdown"""
    parts = []
    parts.append("## 匹配到的表和字段\n")

    for m in retrieval.matches:
        if not m.matched:
            continue
        parts.append(f"### [{m.layer.value}层] {m.table_name}")
        if m.table_comment:
            parts.append(f"表注释: {m.table_comment}")
        parts.append("字段列表:")
        for col in m.columns:
            extra = []
            if col.code_values:
                codes = ", ".join(f"{cv.value}={cv.meaning}" for cv in col.code_values)
                extra.append(f"码值: {codes}")
            if col.data_type:
                extra.append(f"类型: {col.data_type}")
            line = f"  - {col.name}: {col.comment}"
            if extra:
                line += f" ({', '.join(extra)})"
            parts.append(line)
        parts.append("")

    if retrieval.unmatched_concepts:
        parts.append("## 未匹配到的概念（需要标注 TODO）")
        for concept in retrieval.unmatched_concepts:
            parts.append(f"  - {concept}")
        parts.append("")

    return "\n".join(parts)


def _format_assertions(assertions: list) -> str:
    """将断言列表格式化为 LLM prompt 中的约束"""
    parts = ["\n## 已确认的断言条件（必须在 SQL 中使用）\n"]
    parts.append("以下是通过码值匹配确定的 SQL 条件，伪代码中必须使用这些精确值：\n")
    for a in assertions:
        parts.append(f"- **{a.concept_source}** → `{a.sql_condition}` "
                     f"(confidence={a.confidence:.0%})")
    parts.append("")
    return "\n".join(parts)


def generate(
    requirement_text: str,
    retrieval: RetrievalResult,
    concepts: list[BusinessConcept] | None = None,
    assertions: list | None = None,
) -> PseudoCode:
    """生成分析伪代码

    Args:
        requirement_text: 原始需求文档
        retrieval: 检索匹配结果
        concepts: 提取的业务概念（可选）
        assertions: 断言条件列表（可选，来自 assertions.py 的 build_assertions）

    Returns:
        PseudoCode 结构。LLM 调用失败时返回空 steps 的 PseudoCode。
    """
    prompt = build_pseudocode_prompt()
    formatted = _format_matches(retrieval)

    # ── 注入断言条件 ──
    if assertions:
        formatted += _format_assertions(assertions)

    messages = prompt.format_messages(
        requirement=requirement_text,
        matches=formatted,
    )
    system = messages[0].content
    user = messages[1].content

    tracker = TokenTracker()

    try:
        raw = chat_json(
            system_prompt=str(system),
            user_message=str(user),
            callbacks=[tracker],
        )
    except RuntimeError:
        return PseudoCode(
            title="LLM 调用失败",
            steps=[],
            todo_items=["LLM 伪代码生成失败，请手动编写"],
            notes=[f"TokenTracker: {tracker.summary()}"]
        )

    parser = PydanticOutputParser(pydantic_object=PseudoCode)
    return parser.parse(json.dumps(raw, ensure_ascii=False))
