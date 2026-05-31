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


def chat_text(
    system_prompt: str,
    user_message: str,
    *,
    model: str = LLM_MODEL,
    temperature: float = LLM_TEMPERATURE,
    max_retry: int = LLM_MAX_RETRY,
    callbacks: list | None = None,
) -> str:
    """调用 LLM 并返回纯文本（不强制 JSON）

    用于 SQL 修复等不需要结构化输出的场景。
    有 retry 但不要求 JSON 格式。

    Args:
        callbacks: LangChain callbacks 列表（TokenTracker, AuditLogger 等）

    Raises:
        RuntimeError: 超过最大重试次数
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
            )
            content = response.choices[0].message.content

            # 触发 callbacks
            if callbacks:
                _notify_callbacks(callbacks, messages, content, model, response)

            return content.strip() if content else ""
        except Exception as e:
            last_error = e
            if callbacks:
                _notify_callbacks_error(callbacks, e)
            if attempt < max_retry:
                messages.append({
                    "role": "user",
                    "content": f"上次调用失败: {e}。请重试。"
                })

    raise RuntimeError(f"LLM 文本调用失败（重试 {max_retry} 次）: {last_error}")


def chat_json(
    system_prompt: str,
    user_message: str,
    *,
    model: str = LLM_MODEL,
    temperature: float = LLM_TEMPERATURE,
    max_retry: int = LLM_MAX_RETRY,
    callbacks: list | None = None,
) -> dict:
    """调用 LLM 并强制返回 JSON

    Args:
        callbacks: LangChain callbacks 列表（TokenTracker, AuditLogger 等）

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
            result = json.loads(content)

            # 触发 callbacks
            if callbacks:
                _notify_callbacks(callbacks, messages, content, model, response)

            return result
        except (json.JSONDecodeError, Exception) as e:
            last_error = e
            if callbacks:
                _notify_callbacks_error(callbacks, e)
            if attempt < max_retry:
                messages.append({
                    "role": "user",
                    "content": f"上次输出不是合法 JSON，错误: {e}。请确保输出严格合法 JSON，不要有尾随逗号或注释。"
                })

    raise RuntimeError(f"LLM 调用失败（重试 {max_retry} 次）: {last_error}")


def _notify_callbacks(callbacks: list, messages: list, content: str, model: str,
                      api_response=None):
    """通知 callbacks（TokenTracker/AuditLogger 的简化集成）"""
    for cb in callbacks:
        try:
            if hasattr(cb, "on_llm_end"):
                # 构造一个简化的响应对象
                class _FakeResponse:
                    pass
                resp = _FakeResponse()
                # 从 API 响应中提取真实 token_usage
                token_usage = {}
                if api_response and hasattr(api_response, "usage") and api_response.usage:
                    token_usage = {
                        "prompt_tokens": api_response.usage.prompt_tokens or 0,
                        "completion_tokens": api_response.usage.completion_tokens or 0,
                        "total_tokens": api_response.usage.total_tokens or 0,
                    }
                resp.llm_output = {"token_usage": token_usage}
                resp.generations = [[_FakeResponse()]]
                resp.generations[0][0].text = content
                cb.on_llm_end(resp)
        except Exception:
            pass


def _notify_callbacks_error(callbacks: list, error: Exception):
    """通知 callbacks 发生错误"""
    for cb in callbacks:
        try:
            if hasattr(cb, "on_llm_error"):
                cb.on_llm_error(error)
        except Exception:
            pass
