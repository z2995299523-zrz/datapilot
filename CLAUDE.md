# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 一句话理解

传一个业务需求文档 → 自动生成通过测试的 SQL 脚本。如果测试失败 → LLM 诊断 → 自动修复 → 重测。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 API Key（二选一）
set DEEPSEEK_API_KEY=your-key          # Windows
export DEEPSEEK_API_KEY=your-key       # Linux/Mac

# 也可用 .env 文件（config.py 中 load_dotenv 会加载）在项目根目录创建 .env 写入:
#   DEEPSEEK_API_KEY=your-key

# 构建数据字典索引（运行前必需）
python -m dictionary.indexer demo/data_dict.csv

# 运行需求分析
python cli.py search --req demo/req_sample.txt --verbose    # 概念提取 + 分层检索
python cli.py analyze --req demo/req_sample.txt             # 完整链路（概念→检索→伪代码）
python cli.py analyze --req demo/req_sample.txt --sql       # 包含 SQL 生成

# 运行全部测试（210 tests，需设 DEEPSEEK_API_KEY）
pytest tests/ -v

# 运行单个测试文件
pytest tests/test_concept.py -v
pytest tests/test_reconciliation.py -v
pytest tests/test_llm_tester.py -v

# 运行单个测试函数
pytest tests/test_retrieval.py -v -k "test_search_all"

# 启动 Streamlit WebUI
streamlit run ui/app.py
```

## 当前状态

| Phase | 状态 | tests |
|-------|------|-------|
| P1: 需求分析助手 | ✅ | 81 |
| P2: LangChain重构 + SQL生成 | ✅ | 136 |
| P3: 逻辑比对 + LangGraph修复闭环 | ✅ | 210 |
| P4: LangSmith + Streamlit + Demo | ⬜ | — |

## 技术栈

Python 3.12+ / DeepSeek chat (直连) / LangChain 1.x + LangGraph 1.x / ChromaDB / BGE bge-small-zh-v1.5 / Pydantic / Streamlit (P4)

## 全链路架构

```
需求文档.txt
    │
    ▼
Layer 1: 需求 → SQL
  extractor/concept.py    概念提取(LLM/LCEL) → ［entity, dimension, metric, condition］
  retrieval/engine.py     分层检索 DM→DWS→ODS (ChromaDB 语义匹配)
  generator/pseudocode.py 伪代码生成(LLM/LCEL) → PseudoCode{steps:［…］}
  generator/script.py     SQL 代码生成(规则引擎，非 LLM) → 确定性语法转换
    │
    ▼
Layer 2: 三层数据测试
  testing/llm_tester.py   统一 LLM 测试代码生成（表结构+业务逻辑→完整测试SQL套件）
  testing/quality.py      L1 基础质量: 主键唯一/空值率/超长/码值
  testing/comparison.py   L2 逻辑比对: 原始表聚合 vs 结果表聚合
  testing/diagnosis.py    L3 诊断引擎: LLM 五级诊断链路
    │
    ▼ 失败时
Layer 3: LangGraph 修复闭环
  reconciliation/graph.py  StateGraph: run_tests → diagnose → auto_fix → retest (loop)
  reconciliation/nodes.py  各节点函数
  reconciliation/router.py conditional edges 路由逻辑
```

## LLM 调用路径（两条）

**路径 1: `llm_client.chat_json()` / `chat_text()` — 直接调用（测试 mock 目标）**
适合单一输入输出的场景。自带 3 次 retry + JSON 强制。`chat_text()` 用于 SQL 修复等不需结构化输出的场景。

**路径 2: LCEL 链式调用 — LangChain 集成**
```
prompt | llm | parser   (PydanticOutputParser 自动校验)
```
用于概念提取和伪代码生成等需要 PromptTemplate 集中管理的场景。LCEL 路径目前无 retry（脆弱点）。

## 测试 Mock 模式

所有测试不调用真实 LLM API。Mock 目标按模块不同：
- **`llm_client.chat_json/chat_text`** — 大部分测试，mock LLM 返回预定义 dict/str
- **`ChatOpenAI.invoke`** — LCEL 路径的测试（concept.py, pseudocode.py）需要 mock `langchain_openai.ChatOpenAI`

Mock 标准写法（见 `tests/test_concept.py`）：
```python
with mock.patch("llm_client.chat_json", return_value={"concepts": [...]}):
    result = extract_concepts(text)
```

## 目录速查

```
datapilot/
├── config.py                 # HF_ENDPOINT 必须在最顶部 + .env 加载
├── models.py                 # Pydantic 数据模型（TableInfo, PseudoCode, LLMTestCase 等）
├── llm_client.py             # chat_json / chat_text（自带 retry + callbacks）
├── cli.py                    # 命令行入口: search / analyze
├── dictionary/               # loader（Excel/CSV → TableInfo）+ indexer（ChromaDB）
├── extractor/                # prompts.py（所有 ChatPromptTemplate）+ concept.py（LCEL 调用）
├── retrieval/                # engine（DM→DWS→ODS 递进检索）→ matcher → ranker
├── generator/                # pseudocode.py（LLM）+ script.py（规则引擎 SQL 生成）
├── testing/                  # llm_tester.py（统一 LLM） + quality/comparison/diagnosis
├── reconciliation/           # state.py + nodes.py + router.py → graph.py（LangGraph）
├── callbacks/                # token_tracker.py + audit_logger.py
├── demo/                     # data_dict.csv + req_sample.txt
└── tests/                    # 210 tests, pytest
```

## 核心约束

1. `HF_ENDPOINT` 必须在 `config.py` 最顶部 — huggingface_hub 初始化时读取，设晚了无效
2. 所有 LLM 调用走 `chat_json()` / `chat_text()` (自带 retry) 或 LCEL — 不做裸 OpenAI 调用
3. LLM 输出必须 Pydantic 校验 — 失败降级到规则引擎，不依赖乐观解析
4. 新 Prompt → `extractor/prompts.py`；新数据模型 → `models.py` — 不拼字符串、不散落各处
5. 不做全局代理 — DeepSeek 直连；BGE 本地加载

## 开发规范

- LLM 主路径 + 规则 fallback — 不做半成品（参见 memory: `feedback-max-capability`）
- Callbacks (TokenTracker + AuditLogger) 在重要 LLM 调用点接入
- 边界情况有降级路径：LLM 不可用 / retry 耗尽 / 空输入
- 测试流程：先写测试 → 失败 → 最小实现 → 通过
- 代码完成后讲解：实现方式 / 为什么这样实现 / 更好的办法，用 ETL 概念类比
- BGE 模型当前在 indexer.py 和 matcher.py 各加载一次（待合并为共享单例）
- SQL 用规则引擎生成（确定性），测试代码用 LLM 统一生成（语义覆盖）
