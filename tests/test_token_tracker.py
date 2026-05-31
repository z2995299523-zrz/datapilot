"""
测试 TokenTracker — LLM Token 使用追踪
"""
import pytest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callbacks.token_tracker import TokenTracker


class TestTokenTrackerBasics:
    """TokenTracker 基本功能"""

    def test_initial_state(self):
        tracker = TokenTracker()
        assert tracker.total_prompt_tokens == 0
        assert tracker.total_completion_tokens == 0
        assert tracker.total_tokens == 0
        assert tracker.call_count == 0

    def test_on_llm_end_with_token_usage(self):
        """有 token_usage 时的正常累加"""
        tracker = TokenTracker()

        # 构造模拟 LLMResult
        class FakeGen:
            pass

        class FakeResponse:
            pass

        resp = FakeResponse()
        resp.llm_output = {
            "token_usage": {
                "prompt_tokens": 150,
                "completion_tokens": 50,
                "total_tokens": 200,
            }
        }
        gen = FakeGen()
        gen.text = "test output"
        resp.generations = [[gen]]

        tracker.on_llm_end(resp)

        assert tracker.call_count == 1
        assert tracker.total_prompt_tokens == 150
        assert tracker.total_completion_tokens == 50
        assert tracker.total_tokens == 200

    def test_on_llm_end_multiple_calls(self):
        """多次调用累加正确"""
        tracker = TokenTracker()

        class FakeResponse:
            pass

        for i in range(3):
            resp = FakeResponse()
            resp.llm_output = {
                "token_usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 100,
                    "total_tokens": 200,
                }
            }
            resp.generations = [[FakeResponse()]]
            resp.generations[0][0].text = "test"
            tracker.on_llm_end(resp)

        assert tracker.call_count == 3
        assert tracker.total_prompt_tokens == 300
        assert tracker.total_completion_tokens == 300
        assert tracker.total_tokens == 600
        assert len(tracker.call_log) == 3

    def test_on_llm_end_empty_usage(self):
        """API 未返回 usage 时不影响调用"""
        tracker = TokenTracker()

        class FakeResponse:
            pass

        resp = FakeResponse()
        resp.llm_output = {}
        resp.generations = [[FakeResponse()]]
        resp.generations[0][0].text = "test"

        tracker.on_llm_end(resp)
        # 不应抛出异常
        assert tracker.call_count == 1
        assert tracker.total_tokens == 0

    def test_on_llm_end_no_llm_output(self):
        """无 llm_output 时使用 fallback"""
        tracker = TokenTracker()

        class FakeResponse:
            pass

        resp = FakeResponse()
        resp.llm_output = None
        resp.generations = [[FakeResponse()]]
        resp.generations[0][0].text = "test"

        # 不应抛出异常
        tracker.on_llm_end(resp)

    def test_on_llm_end_no_generations(self):
        """无 generations 时回退到 0"""
        tracker = TokenTracker()

        class FakeResponse:
            pass

        resp = FakeResponse()
        resp.llm_output = {}
        resp.generations = []

        tracker.on_llm_end(resp)
        assert tracker.call_count == 1
        assert tracker.total_tokens == 0

    def test_summary_format(self):
        """summary() 返回完整统计"""
        tracker = TokenTracker()

        class FakeResponse:
            pass

        resp = FakeResponse()
        resp.llm_output = {
            "token_usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "total_tokens": 1500,
            }
        }
        resp.generations = [[FakeResponse()]]
        resp.generations[0][0].text = "test"
        tracker.on_llm_end(resp)

        summary = tracker.summary()
        assert summary["total_calls"] == 1
        assert summary["total_prompt_tokens"] == 1000
        assert summary["total_completion_tokens"] == 500
        assert summary["total_tokens"] == 1500
        assert "estimated_cost_usd" in summary

    def test_call_log_entries(self):
        """call_log 记录每次调用"""
        tracker = TokenTracker()

        class FakeResponse:
            pass

        resp = FakeResponse()
        resp.llm_output = {
            "token_usage": {
                "prompt_tokens": 200,
                "completion_tokens": 80,
                "total_tokens": 280,
            }
        }
        resp.generations = [[FakeResponse()]]
        resp.generations[0][0].text = "output"
        tracker.on_llm_end(resp)

        assert len(tracker.call_log) == 1
        entry = tracker.call_log[0]
        assert entry["call"] == 1
        assert entry["prompt_tokens"] == 200
        assert entry["completion_tokens"] == 80


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
