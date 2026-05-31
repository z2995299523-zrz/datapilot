"""
业务概念提取器

架构: LangChain PromptTemplate（prompt 管理）+ chat_json（自带 3 次 retry）+ PydanticOutputParser（schema 校验）

为什么不用纯 LCEL: prompt | llm | parser 在 DeepSeek 输出格式不稳定时，parser 抛异常没有
重试机制。chat_json() 会把解析错误反馈给 LLM 自纠正，最多重试 3 次。
"""
import json
from langchain_core.output_parsers import PydanticOutputParser

from models import BusinessConcept, ConceptType, ConceptExtractionResult
from extractor.prompts import build_concept_prompt
from llm_client import chat_json
from callbacks.token_tracker import TokenTracker


def extract_concepts(requirement_text: str) -> ConceptExtractionResult:
    """从需求文档中提取业务概念

    Args:
        requirement_text: 需求文档全文

    Returns:
        ConceptExtractionResult 包含提取的业务概念列表。LLM 调用失败时返回空 concepts。
    """
    prompt = build_concept_prompt()
    messages = prompt.format_messages(requirement_text=requirement_text)
    system = messages[0].content
    user = messages[1].content

    tracker = TokenTracker()

    try:
        raw = chat_json(
            system_prompt=str(system),
            user_message=str(user),
            callbacks=[tracker],
        )
    except RuntimeError as e:
        return ConceptExtractionResult(
            concepts=[],
            raw_requirement=requirement_text,
            llm_error=str(e),
            llm_token_usage=tracker.summary(),
        )

    parser = PydanticOutputParser(pydantic_object=ConceptExtractionResult)
    result = parser.parse(json.dumps(raw, ensure_ascii=False))
    result.raw_requirement = requirement_text
    result.llm_token_usage = tracker.summary()
    return result
