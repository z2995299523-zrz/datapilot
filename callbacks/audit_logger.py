"""
LLM 调用审计日志 — LangChain BaseCallbackHandler

记录每次 LLM 推理的输入/输出，支持审计追溯。
"""
import time
from langchain_core.callbacks import BaseCallbackHandler
from typing import Any


class AuditLogger(BaseCallbackHandler):
    """记录每次 LLM 调用的输入输出 — 审计追溯

    用法:
        llm = ChatOpenAI(callbacks=[AuditLogger()])
    """

    def __init__(self):
        super().__init__()
        self.records: list[dict] = []
        self._current_start: float | None = None

    def on_llm_start(
        self, serialized: dict[str, Any], prompts: list[str], **kwargs
    ) -> None:
        self._current_start = time.time()

    def on_llm_end(self, response, **kwargs) -> None:
        elapsed = 0.0
        if self._current_start is not None:
            elapsed = round(time.time() - self._current_start, 3)

        # 提取 prompt 和 completion
        prompt_text = ""
        completion_text = ""
        if hasattr(response, "generations") and response.generations:
            gen = response.generations[0][0]
            if hasattr(gen, "message"):
                prompt_text = str(gen.message.content)[:500]
            if hasattr(gen, "text"):
                completion_text = gen.text[:1000]

        self.records.append({
            "timestamp": time.time(),
            "model": kwargs.get("invocation_params", {}).get("model", "unknown"),
            "elapsed_seconds": elapsed,
            "prompt_preview": prompt_text,
            "completion_preview": completion_text,
        })

    def on_llm_error(self, error: Exception, **kwargs) -> None:
        self.records.append({
            "timestamp": time.time(),
            "error": str(error),
        })

    def summary(self) -> dict:
        return {
            "total_calls": len(self.records),
            "errors": sum(1 for r in self.records if "error" in r),
            "total_elapsed_seconds": round(
                sum(r.get("elapsed_seconds", 0) for r in self.records), 3
            ),
        }
