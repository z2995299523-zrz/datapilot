"""
LLM 调用封装 — DeepSeek (OpenAI 兼容)

使用方式:
    # 新（推荐）: 构造器注入，可 mock
    from services.config import AppConfig
    config = AppConfig.from_env()
    client = DeepSeekClient(config)
    result = client.chat_json(system, user)

    # 旧（兼容）: 模块级函数，测试 mock 目标
    from llm_client import chat_json, chat_text
    result = chat_json(system, user)     # 仍然有效

    # LangChain 集成: LCEL 链式组合
    chat_model = client.get_chat_model() # 或 get_chat_model()
"""
import json
from openai import OpenAI
from langchain_openai import ChatOpenAI
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_RETRY


# ============================================================================
# DeepSeekClient — 可注入的 LLM 客户端
# ============================================================================

class DeepSeekClient:
    """DeepSeek LLM 客户端 — 可注入，可 mock

    接受 AppConfig 或独立参数。实例级懒加载，非模块级单例。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_retry: int | None = None,
    ):
        self.api_key = api_key or LLM_API_KEY
        self.base_url = base_url or LLM_BASE_URL
        self.model = model or LLM_MODEL
        self.temperature = temperature if temperature is not None else LLM_TEMPERATURE
        self.max_retry = max_retry if max_retry is not None else LLM_MAX_RETRY

        self._client: OpenAI | None = None
        self._chat_model: ChatOpenAI | None = None

    def _get_openai_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def get_chat_model(self) -> ChatOpenAI:
        """获取 LangChain ChatOpenAI 实例（实例级懒加载）"""
        if self._chat_model is None:
            self._chat_model = ChatOpenAI(
                model=self.model,
                api_key=self.api_key,
                base_url=self.base_url,
                temperature=self.temperature,
            )
        return self._chat_model

    # ── 公共调用接口 ──

    def chat_text(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_retry: int | None = None,
        callbacks: list | None = None,
    ) -> str:
        """调用 LLM 并返回纯文本（不强制 JSON）"""
        client = self._get_openai_client()
        _model = model or self.model
        _temp = temperature if temperature is not None else self.temperature
        _retry = max_retry if max_retry is not None else self.max_retry

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        last_error = None
        for attempt in range(1, _retry + 1):
            try:
                response = client.chat.completions.create(
                    model=_model, messages=messages, temperature=_temp,
                )
                content = response.choices[0].message.content
                if callbacks:
                    _notify_callbacks(callbacks, messages, content, _model, response)
                return content.strip() if content else ""
            except Exception as e:
                last_error = e
                if callbacks:
                    _notify_callbacks_error(callbacks, e)
                if attempt < _retry:
                    messages.append({
                        "role": "user",
                        "content": f"上次调用失败: {e}。请重试。",
                    })

        raise RuntimeError(f"LLM 文本调用失败（重试 {_retry} 次）: {last_error}")

    def chat_json(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_retry: int | None = None,
        callbacks: list | None = None,
    ) -> dict:
        """调用 LLM 并强制返回 JSON"""
        client = self._get_openai_client()
        _model = model or self.model
        _temp = temperature if temperature is not None else self.temperature
        _retry = max_retry if max_retry is not None else self.max_retry

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        last_error = None
        for attempt in range(1, _retry + 1):
            try:
                response = client.chat.completions.create(
                    model=_model, messages=messages, temperature=_temp,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
                result = json.loads(content)
                if callbacks:
                    _notify_callbacks(callbacks, messages, content, _model, response)
                return result
            except (json.JSONDecodeError, Exception) as e:
                last_error = e
                if callbacks:
                    _notify_callbacks_error(callbacks, e)
                if attempt < _retry:
                    messages.append({
                        "role": "user",
                        "content": (
                            f"上次输出不是合法 JSON，错误: {e}。"
                            "请确保输出严格合法 JSON，不要有尾随逗号或注释。"
                        ),
                    })

        raise RuntimeError(f"LLM 调用失败（重试 {_retry} 次）: {last_error}")


# ============================================================================
# 兼容层 — 模块级函数（保留给旧代码和测试 mock）
# ============================================================================

_default_client: DeepSeekClient | None = None


def _get_default_client() -> DeepSeekClient:
    """获取默认客户端实例（惰性创建，供兼容层使用）"""
    global _default_client
    if _default_client is None:
        _default_client = DeepSeekClient()
    return _default_client


def _get_client() -> OpenAI:
    """# Deprecated: 使用 DeepSeekClient 实例替代"""
    return _get_default_client()._get_openai_client()


def get_chat_model() -> ChatOpenAI:
    """# Deprecated: 使用 DeepSeekClient 实例替代"""
    return _get_default_client().get_chat_model()


def chat_text(
    system_prompt: str,
    user_message: str,
    *,
    model: str = LLM_MODEL,
    temperature: float = LLM_TEMPERATURE,
    max_retry: int = LLM_MAX_RETRY,
    callbacks: list | None = None,
) -> str:
    """# Deprecated: 使用 DeepSeekClient 实例替代"""
    return _get_default_client().chat_text(
        system_prompt, user_message,
        model=model, temperature=temperature, max_retry=max_retry,
        callbacks=callbacks,
    )


def chat_json(
    system_prompt: str,
    user_message: str,
    *,
    model: str = LLM_MODEL,
    temperature: float = LLM_TEMPERATURE,
    max_retry: int = LLM_MAX_RETRY,
    callbacks: list | None = None,
) -> dict:
    """# Deprecated: 使用 DeepSeekClient 实例替代"""
    return _get_default_client().chat_json(
        system_prompt, user_message,
        model=model, temperature=temperature, max_retry=max_retry,
        callbacks=callbacks,
    )


# ============================================================================
# Callback 通知（内部使用）
# ============================================================================

def _notify_callbacks(callbacks: list, messages: list, content: str, model: str,
                      api_response=None):
    """通知 callbacks（TokenTracker/AuditLogger 的简化集成）"""
    for cb in callbacks:
        try:
            if hasattr(cb, "on_llm_end"):
                class _FakeResponse:
                    pass
                resp = _FakeResponse()
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
