"""
Token 消耗追踪 — LangChain BaseCallbackHandler

记录每次 LLM 调用的 Token 使用量，用于成本分析。
"""
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


class TokenTracker(BaseCallbackHandler):
    """追踪每次 LLM 调用的 Token 消耗

    用法:
        llm = ChatOpenAI(callbacks=[TokenTracker()])
    """

    def __init__(self):
        super().__init__()
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.call_count = 0
        self.call_log: list[dict] = []

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        """LLM 调用结束时记录 token 用量"""
        if response.llm_output and "token_usage" in response.llm_output:
            usage = response.llm_output["token_usage"]
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total = usage.get("total_tokens", prompt_tokens + completion_tokens)
        elif response.generations:
            # fallback: 从 generation 估算
            llm_output = response.llm_output or {}
            usage = llm_output.get("token_usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total = prompt_tokens + completion_tokens
        else:
            prompt_tokens = 0
            completion_tokens = 0
            total = 0

        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_tokens += total
        self.call_count += 1
        self.call_log.append({
            "call": self.call_count,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total,
        })

    def summary(self) -> dict:
        return {
            "total_calls": self.call_count,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self._estimate_cost(),
        }

    def _estimate_cost(self) -> float:
        """估算 DeepSeek 成本（参考 deepseek-chat 定价）"""
        # deepseek-chat: $0.14/1M input, $0.28/1M output
        input_cost = self.total_prompt_tokens / 1_000_000 * 0.14
        output_cost = self.total_completion_tokens / 1_000_000 * 0.28
        return round(input_cost + output_cost, 6)
