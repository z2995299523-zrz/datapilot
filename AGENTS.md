# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

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

# 构建银行数据字典（11 表/76 字段）
python -m dictionary.indexer demo/bank_data_dict.csv

# 运行需求分析
python cli.py analyze --req demo/req_sample.txt             # 完整链路（概念→检索→伪代码）
python cli.py analyze --req demo/req_sample.txt --sql       # 包含 SQL 生成
python cli.py analyze --req demo/bank_req_aml.txt --dict demo/bank_data_dict.csv --sql  # 银行测试

# 启动 Streamlit WebUI（用安全启动器，避免 BGE segfault）
python run_ui.py
# 或直接启动（可能遇到 BGE + CUDA 冲突 crash）
streamlit run ui/app.py

# 运行全部测试（294 tests，需设 DEEPSEEK_API_KEY）
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
| P4: LangSmith + Streamlit + Demo | ✅ | — |

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
└── tests/                    # 292 tests, pytest
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

## 行为准则

### 1. 编码前：停下来想

- **明确假设** — 如果需求有歧义，列出 2-3 种解读，让用户选，不要自己默默猜
- **指出更简单的方案** — 如果用户要的方案过于复杂，主动提出替代路径
- **不确定就说不知道** — 不要假装理解，停下来确认

> 来源：andrej-karpathy-skills "Think Before Coding"

### 2. 改动时：最小扩散

- **每行改动都能追溯到需求** — 不顺手重构不相干的代码、不改旁边的格式、不删看起来"没用"的东西
- **看到烂代码？提出来，但不动** — 让用户决定是否另开任务处理
- **改名/改签名 → 全仓库搜索引用** — 包括 import、字符串字面量、测试 mock 路径、`__init__.py` 重导出

> 来源：andrej-karpathy-skills "Surgical Changes" + agent-md "Edit Safety"

### 3. 完成后：三层验证

| 层 | 做什么 | 什么时候必须 |
|----|--------|-------------|
| Text | pytest + ruff 通过 | 每次改动 |
| Runtime | 改过的 CLI/Script 实际跑一遍 | 改了可执行路径 |
| Visual | Streamlit UI 截图 | 改了 UI 组件 |

**不要只靠代码审查就声称完成。** 测试全绿 ≠ 真的能跑。

> 来源：agent-md "Verification"

### 4. 被纠正后：写 gotcha（有门禁）

被纠正后，先过三道门禁，再决定是否写入 `memory/gotchas.md`：

**门禁 1 — 是可复用的模式吗？**
- ✅ 值得记录：揭示了系统性知识缺口，同样错误可能再犯（如 mock 路径规则、BGE 加载顺序）
- ❌ 不记录：一次性 typo、变量名改个拼写、这次特有的偶然失误

**门禁 2 — 已存在吗？**
- 写入前先 `Grep` 搜索 `memory/gotchas.md` 中是否已有类似条目
- 有 → 更新已有条目（补充现象/根因），不创建重复项
- 无 → 新建

**门禁 3 — 至少包含根因 + 教训**
- 只写现象（"XX 出错了"）→ 不合格，必须挖到根因
- 根因不清楚 → 先 debug，搞清楚再写

```markdown
---
name: <kebab-case>
description: <一句话触发条件>
metadata:
  type: gotcha
---

**现象:** 看到什么
**根因:** 为什么发生
**教训:** 以后怎么做
```

已有的 gotchas（BGE segfault、`assert` 关键字、qualifier 无空格 `=` 等）从 `reference_pitfalls.md` 迁移到了 `memory/gotchas.md`。这是活的文档。

> 来源：agent-md "Self-Correction"
