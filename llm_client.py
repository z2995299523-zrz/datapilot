"""
LLM 调用封装 — DeepSeek (OpenAI 兼容)

两种调用方式：
1. chat_json() — 原始 OpenAI 调用，手写重试（v2.0 兼容，测试 mock 目标）
2. get_chat_model() → ChatOpenAI — LangChain 集成（v3.0）
"""
import json
from openai import OpenAI
from langchain_openai import ChatOpenAI
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_RETRY


_client: OpenAI | None = None
_chat_model: ChatOpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    return _client


def get_chat_model() -> ChatOpenAI:
    """获取 LangChain ChatOpenAI 实例（全局单例）

    用于 LCEL 链式组合: prompt | llm | parser
    """
    global _chat_model
    if _chat_model is None:
        _chat_model = ChatOpenAI(
            model=LLM_MODEL,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            temperature=LLM_TEMPERATURE,
        )
    return _chat_model


def chat_json(
    system_prompt: str,
    user_message: str,
    *,
    model: str = LLM_MODEL,
    temperature: float = LLM_TEMPERATURE,
    max_retry: int = LLM_MAX_RETRY,
) -> dict:
    """调用 LLM 并强制返回 JSON

    Raises:
        RuntimeError: 超过最大重试次数仍无法解析 JSON
    """
    client = _get_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    last_error = None
    for attempt in range(1, max_retry + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except (json.JSONDecodeError, Exception) as e:
            last_error = e
            if attempt < max_retry:
                messages.append({
                    "role": "user",
                    "content": f"上次输出不是合法 JSON，错误: {e}。请确保输出严格合法 JSON，不要有尾随逗号或注释。"
                })

    raise RuntimeError(f"LLM 调用失败（重试 {max_retry} 次）: {last_error}")
