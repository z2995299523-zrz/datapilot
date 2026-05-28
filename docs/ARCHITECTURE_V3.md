# DataPilot v3.0 架构文档

> **版本**: v3.0 | **日期**: 2026-05-28 | **状态**: 已确认

---

## 一、技术栈总览

### 面试技能矩阵

| 技术 | 用途 | 对应岗位要求 |
|------|------|-------------|
| **LangGraph** | 修复闭环状态图（StateGraph + conditional edges + checkpointer） | 必考 |
| **LangChain** | PromptTemplate / OutputParser / RunnableSequence / Callbacks | 必考 |
| **LangSmith** | 全链路 LLM 调用 trace + 可视化调试 | 加分 |
| **ChromaDB** | 数据字典向量库 + metadata filtering | 向量数据库经验 |
| **BGE Embedding** | 本地中文语义匹配模型 | Embedding 工程能力 |
| **Pydantic** | 全链路数据契约（State Schema + LLM Output 校验） | 结构化输出 |
| **DeepSeek** | LLM 推理（OpenAI 兼容协议） | 多模型适配 |
| **Streamlit** | WebUI | 演示能力 |
| **HermesAgent** | 框架评估与选型分析 | 框架评估能力 |

---

## 二、产品定位

### 一句话

**打通 "业务需求 → 模型匹配 → 脚本生成 → 数据测试 → 逻辑核对 → 修复闭环" 的全流程需求开发引擎，基于 LangGraph + LangChain 构建。**

### 解决的核心问题

```
需求分析 → 模型定位 → 脚本开发 → 数据测试 → 逻辑核对 → 修复 → 上线
```

**痛点不是某一步，而是每一步之间的断层：**

| 环节 | 谁做 | 问题 |
|------|------|------|
| 需求分析 → 模型定位 | 分析人员 | 不熟悉数仓模型，耗 1-3 天，容易遗漏 |
| 模型定位 → 脚本开发 | 开发人员 | 分析结论传递失真，理解偏差 |
| 脚本开发 → 数据测试 | 测试人员 | 测试用例靠人工写，覆盖不全 |
| 数据测试 → 逻辑核对 | 分析人员 | 发现问题后需回溯到需求分析，手工重来 |
| 逻辑核对 → 修复 | 全部 | 跨角色沟通成本高，反复对齐 |

---

## 三、框架选型：为什么分层使用

### 核心原则：框架用在真正需要的地方，不为关键词硬套

```
DataPilot v3.0 技术架构分层：

┌──────────────────────────────────────────────────────┐
│  Layer 3: 修复闭环（图编排）                          │
│  → LangGraph StateGraph + conditional edges          │
│  → checkpointer 持久化 + streaming 实时输出           │
│  → 对应岗位要求: LangGraph 实战经验                    │
├──────────────────────────────────────────────────────┤
│  Layer 2: LLM 交互（链式调用）                        │
│  → LangChain ChatPromptTemplate / OutputParser       │
│  → chat_json() 自带 3 次 retry 保证容错              │
│  → LangSmith Callbacks 全链路 trace                  │
│  → 对应岗位要求: LangChain + LangSmith                │
├──────────────────────────────────────────────────────┤
│  Layer 1: 线性 Pipeline（纯 Python + Pydantic）        │
│  → 概念提取 → 分层检索 → 伪代码 → 脚本生成            │
│  → 每步纯函数，输入/输出 Pydantic，可独立测试          │
│  → LangChain 仅用于 PromptTemplate 管理，不依赖其编排  │
│  → 面试话术: "用 LangChain 的组件做能做的事，不用它做做不了的事" │
└──────────────────────────────────────────────────────┘
```

**实际上 LangChain 用在哪、不用在哪：**

| 模块 | 用了 LangChain 什么 | 理由 |
|------|-------------------|------|
| `extractor/prompts.py` | `ChatPromptTemplate` | 集中管理 Prompt，`format_instructions` 自动注入 |
| `extractor/concept.py` | `PydanticOutputParser`（仅 schema 校验） | LLM 调用走 `chat_json`（自带 retry），Parser 只做校验 |
| `generator/pseudocode.py` | 同上 | 同上 |
| `callbacks/` | `BaseCallbackHandler` | Token 追踪 + 审计日志 |
| `reconciliation/`（待实现） | LangGraph `StateGraph` | 图编排是 LangGraph 的精准场景 |
| **其他所有模块** | **纯 Python** | 检索、脚本生成、测试引擎不需要 LLM 编排 |

### 为什么不选 HermesAgent / OpenClaw

| 框架 | 评估结论 |
|------|----------|
| **HermesAgent** | Python 同语言、OpenAI 兼容，但定位是 RL 训练框架 + 对话 Agent，DataPilot 只需要其 5% 的功能。在项目选型文档中评估并记录决策过程，体现框架评估能力 |
| **OpenClaw** | Node.js 生态（DataPilot 全栈 Python），核心能力是消息网关和系统自动化，与数据分析工作流完全不匹配 |

**关键结论**：Agent 框架假设 "给一个目标，让 AI 自己规划步骤"。DataPilot 的步骤是固定的（DM→DWS→ODS 不可绕过），本质是 Workflow Engine 而非 Autonomous Agent。但修复闭环（条件路由 + 循环重试）天然适合图编排，这正是 LangGraph 的精准场景。

---

## 四、全链路架构

```
                        需求文档.txt
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ 概念提取  │  │ 数据字典  │  │ 规则库   │
        │ (LLM)    │  │ (ChromaDB)│  │          │
        └────┬─────┘  └────┬─────┘  └────┬─────┘
             │             │              │
             └─────────────┼──────────────┘
                           │
         ┌─────────────────▼──────────────────┐
         │  LangChain LCEL (RunnableSequence)  │
         │  extract | search | pseudocode      │
         └─────────────────┬──────────────────┘
                           │
              ╔════════════╧════════════╗
              ║   v3.0 新增模块         ║
              ╠════════════╤════════════╣
              ║            │            ║
              ║  ┌─────────▼─────────┐  ║
              ║  │  脚本生成引擎      │  ║
              ║  │  伪代码 → SQL     │  ║
              ║  └─────────┬─────────┘  ║
              ║            │            ║
              ║  ┌─────────▼─────────┐  ║
              ║  │  数据测试引擎      │  ║
              ║  │  三层测试体系      │  ║
              ║  └─────────┬─────────┘  ║
              ║            │ 失败       ║
              ║  ┌─────────▼─────────┐  ║
              ║  │  LangGraph 闭环   │  ║
              ║  │  诊断 → 修复 →    │  ║
              ║  │  重匹配 → 重测试  │  ║
              ║  └───────────────────┘  ║
              ╚═════════════════════════╝
                           │
                    ┌──────▼──────┐
                    │  上线报告   │
                    └─────────────┘
```

---

## 五、框架集成详设

### 5.1 LangChain 集成点

**不是全项目建在 LangChain 上——只取真正有用的组件：**

#### PromptTemplate — 统一管理 LLM Prompt

```python
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser

# 概念提取 Prompt
concept_prompt = ChatPromptTemplate.from_messages([
    ("system", EXTRACTION_SYSTEM_PROMPT),
    ("human", "需求文档:\n{requirement_text}"),
])

# 伪代码生成 Prompt
pseudocode_prompt = ChatPromptTemplate.from_messages([
    ("system", PSEUDOCODE_SYSTEM_PROMPT),
    ("human", "需求:\n{requirement}\n\n匹配结果:\n{matches}"),
])

# 诊断推理 Prompt
diagnosis_prompt = ChatPromptTemplate.from_messages([
    ("system", DIAGNOSIS_SYSTEM_PROMPT),
    ("human", "测试异常:\n{failures}\n\n上下文:\n{context}"),
])
```

#### PydanticOutputParser — LLM 输出结构化校验

```python
from langchain.output_parsers import PydanticOutputParser

concept_parser = PydanticOutputParser(pydantic_object=ConceptExtractionResult)
pseudocode_parser = PydanticOutputParser(pydantic_object=PseudoCode)
diagnosis_parser = PydanticOutputParser(pydantic_object=DiagnosisResult)

# 自动注入 format_instructions 到 prompt
# "你必须输出以下 JSON 格式: {schema}"
```

#### LCEL RunnableSequence — 链式声明

```python
from langchain.schema.runnable import RunnableSequence, RunnableLambda

extract_chain = concept_prompt | llm | concept_parser
search_chain = RunnableLambda(search_layers)
pseudocode_chain = pseudocode_prompt | llm | pseudocode_parser

# 面试展示: 一行代码声明完整链路
analysis_pipeline = extract_chain | search_chain | pseudocode_chain
```

#### Callbacks — LLM 调用生命周期

```python
from langchain.callbacks import BaseCallbackHandler

class TokenTracker(BaseCallbackHandler):
    """追踪每次 LLM 调用的 Token 消耗"""
    def on_llm_end(self, response, **kwargs):
        # 记录 token 使用量 → 用于成本分析
        pass

class AuditLogger(BaseCallbackHandler):
    """记录每次 LLM 推理的输入输出 → 审计追溯"""
    pass
```

### 5.2 LangGraph — 修复闭环（核心亮点）

**为什么用 LangGraph：** 修复闭环是带条件分支的循环图，不是线性管道。LangGraph 的 StateGraph + conditional edges + checkpointer 天然解决。

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from typing import TypedDict, Literal
from models import TestResult, DiagnosisResult, Report


class ReconciliationState(TypedDict):
    """修复闭环的状态 Schema — LangGraph 的 State 即文档"""
    script_sql: str
    test_results: list[TestResult]
    diagnosis: DiagnosisResult | None
    fix_history: list[str]
    retry_count: int
    final_report: Report | None


def build_reconciliation_graph() -> StateGraph:
    graph = StateGraph(ReconciliationState)

    # 注册节点 — 每个节点是一个可独立测试的纯函数
    graph.add_node("run_tests", run_all_tests)
    graph.add_node("diagnose", diagnose_failures)
    graph.add_node("auto_fix", apply_automatic_fix)
    graph.add_node("human_review", generate_review_report)

    graph.set_entry_point("run_tests")

    # conditional edges: LangGraph 的核心价值
    graph.add_conditional_edges(
        "run_tests",
        route_by_test_result,
        {
            "pass": END,          # 通过 → 结束
            "fail": "diagnose",   # 失败 → 诊断
        },
    )

    graph.add_conditional_edges(
        "diagnose",
        route_by_fixability,
        {
            "auto": "auto_fix",        # 可自动 → 修复
            "manual": "human_review",  # 不可自动 → 人工
        },
    )

    graph.add_edge("auto_fix", "run_tests")   # 闭环！
    graph.add_edge("human_review", END)

    return graph.compile(checkpointer=MemorySaver())


# 流式执行 — 实时看到修复过程
async for event in graph.astream(initial_state):
    # 面试时直接演示: 测试失败 → 诊断 → 自动修复 → 重测通过
    print(event)
```

**LangGraph 价值总结（面试话术）：**

1. **StateGraph + TypedDict**：修复状态是类型安全的 Python dict，不需要学自定义 DSL
2. **conditional edges**：测试通过/失败的分支逻辑是显式声明的图边，不是藏在 if/else 里的魔法
3. **checkpointer**：每次修复→重测试的状态都被持久化。甲方审计时回溯 "这个字段为什么改了三次才通过"
4. **streaming**：`graph.astream()` 实时输出修复过程，给甲方演示比静态报告有冲击力

### 5.3 LangSmith — 全链路 Trace

**集成方式**：LangChain Callbacks 自动上报，无需侵入业务代码。

```python
# 设置环境变量即可
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_API_KEY=...
# LANGCHAIN_PROJECT=datapilot

# 每次 LLM 调用自动 trace:
#   概念提取 LLM调用  [234 tokens, 1.2s]
#     ├── 输入: 需求文档 (500字)
#     ├── 输出: 5 个概念 (Pydantic ✅)
#     └── Token: 234
#
#   伪代码生成 LLM调用  [567 tokens, 3.1s]
#     ├── 输入: 检索结果
#     ├── 输出: 3 个步骤 (Pydantic ✅)
#     └── Token: 567
#
#   诊断推理 LLM调用  [432 tokens, 2.4s]
#     ├── 根因: 码值不匹配 (置信度 0.92)
#     ├── 决策: 自动修复
#     └── Token: 432
```

**面试展示**：直接打开 LangSmith 网页，展示全链路 Trace 树状图。

---

## 六、新增业务模块详设

### 6.1 脚本生成引擎（`generator/script.py`）

**输入**：伪代码 + 匹配结果 + 数据字典

**输出**：可执行的 SQL 脚本

**映射逻辑**：

```
PseudoCodeStep → SQL 子句映射：
  source_table  → FROM {table}
  conditions    → WHERE {cond1} AND {cond2}
  joins         → LEFT JOIN {right} ON {left}.key = {right}.key
  aggregations  → GROUP BY + {agg1}, {agg2}
  output        → SELECT {fields}
```

| 决策 | 选型 | 理由 |
|------|------|------|
| 语言 | SQL 优先 | 数据库原生执行、执行计划可分析、测试可直接验证 |
| JOIN 键推断 | 数据字典 `relations` + LLM | relations 是 ground truth，LLM 补充未标注的推断 |
| 多层降级 | DM 直接用；ODS 自动加 GROUP BY | 降级后产出等效粒度的结果 |
| 模板 | LangChain PromptTemplate + Jinja2 | 结构约束保证语法正确 |

### 6.2 数据测试引擎（`testing/` 三层体系）

#### 第一层：基础数据质量

元数据驱动，零 LLM 调用。只读结果表。

| 检查项 | 实现 | 来源 |
|--------|------|------|
| 主键唯一性 | `COUNT(*) != COUNT(DISTINCT pk)` | `is_primary_key` |
| 空值率 | `SUM(col IS NULL) / COUNT(*)` vs 阈值 | `column_type` |
| 字段超长 | `MAX(LENGTH(col))` vs varchar(N)*2 | `column_type` |
| 码值合法性 | `DISTINCT col NOT IN (合法值列表)` | `code_values` |

#### 第二层：逻辑结果比对

从伪代码反向推导验证 SQL：

```
伪代码: "按渠道统计活跃客户数，COUNT(DISTINCT cust_id)"
   ↓ 反向推导
验证SQL: 取 ODS/DWS 原始表，按 channel_type GROUP BY，COUNT(DISTINCT cust_id)
   ↓
与脚本输出结果表逐行比对
```

| 聚合类型 | 验证方法 |
|----------|----------|
| COUNT / SUM | 原始表聚合 vs 结果表值 |
| COUNT DISTINCT | 原始表去重计数 vs 结果表 |
| MAX / MIN | 原始表极值 vs 结果表值域 |
| GROUP BY | 原始表维度组合 vs 结果表覆盖 |

#### 第三层：脚本逻辑核对（LangGraph 诊断节点）

五级诊断链路：

```
Level 1: 数据源 → Level 2: 码值 → Level 3: JOIN
→ Level 4: 业务口径 → Level 5: 概念遗漏 → 回溯需求分析
```

每级输出 `DiagnosisResult`：

```python
class DiagnosisResult(BaseModel):
    level: int                  # 诊断层级
    root_cause: str             # 根因分类
    confidence: float           # 置信度 0-1
    evidence: list[str]         # 证据链
    fixable_automatically: bool
    suggested_fix: str
```

### 6.3 修复闭环（LangGraph StateGraph）

```
测试失败 → 诊断
              ├─ 可自动: 码值替换/CAST转换/补充条件
              │          → 重生成脚本 → 重测试 → 收敛或升级
              └─ 不可自动: 概念遗漏/口径不一致
                          → 人工确认报告 → 修正字典/需求 → 重跑全链路
```

终止条件：全部通过 / 不可自动修复已报告 / 重试超过 3 次

---

## 七、目录结构（v3.0）

```
datapilot/
├── config.py
├── models.py               # Pydantic 模型 + LangGraph State Schema
├── llm_client.py
├── cli.py
│
├── dictionary/
│   ├── loader.py
│   ├── indexer.py
│   └── validator.py        # (new)
│
├── extractor/
│   ├── concept.py          # 改为 LangChain PromptTemplate
│   ├── prompts.py          # (new) 集中管理 LLM Prompt
│   └── rules.py            # (new) 业务规则库
│
├── retrieval/
│   ├── engine.py
│   ├── matcher.py
│   └── ranker.py
│
├── generator/
│   ├── pseudocode.py       # 改为 LangChain PromptTemplate
│   ├── script.py           # (new) SQL 脚本生成
│   └── templates/          # (new) Jinja2 模板
│
├── testing/                # (new)
│   ├── quality.py          # L1: 基础数据质量
│   ├── comparison.py       # L2: 逻辑结果比对
│   ├── diagnosis.py        # L3: 诊断引擎 (LangChain prompt)
│   ├── connection.py       # 数据库连接抽象层
│   ├── report.py           # 测试报告生成
│   └── rules/              # 测试规则库
│
├── reconciliation/         # (new) LangGraph 修复闭环
│   ├── graph.py            # StateGraph 定义 + 编译
│   ├── nodes.py            # 节点函数 (run_tests, diagnose, auto_fix)
│   ├── router.py           # conditional edges 路由逻辑
│   └── report.py           # 上线报告
│
├── callbacks/              # (new) LangChain Callbacks
│   ├── token_tracker.py    # Token 消耗追踪
│   └── audit_logger.py     # LLM 调用审计日志
│
├── ui/
│   └── app.py              # Streamlit
│
├── demo/
│   ├── data_dict.csv
│   ├── req_sample.txt
│   └── generate_dict.py
│
└── tests/
    ├── test_loader.py
    ├── test_indexer.py
    ├── test_concept.py
    ├── test_retrieval.py
    ├── test_pseudocode.py
    ├── test_script.py      # (new)
    ├── test_quality.py     # (new)
    ├── test_comparison.py  # (new)
    ├── test_diagnosis.py   # (new)
    ├── test_reconciliation.py  # (new) LangGraph state test
    └── test_integration.py
```

---

## 八、模块依赖图

```
                     ┌─────────────┐
                     │  models.py  │ ← Pydantic + LangGraph State Schema
                     └──────┬──────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
    ┌────▼────┐    ┌────────▼────────┐   ┌─────▼──────┐
    │dictionary│    │ extractor/prompts│   │ LangSmith  │
    └────┬────┘    │ (LangChain)      │   │ (trace)    │
         │         └────────┬────────┘   └────────────┘
         │                  │
         └────────┬─────────┘
                  │
          ┌───────▼───────┐
          │   retrieval   │
          └───────┬───────┘
                  │
          ┌───────▼───────┐
          │  pseudocode   │ (LangChain PromptTemplate)
          └───────┬───────┘
                  │
       ┌──────────┼──────────┐
       │          │          │
  ┌────▼───┐ ┌───▼────┐ ┌───▼──────────┐
  │ script │ │testing │ │reconciliation │
  │        │ │        │ │ (LangGraph)   │
  └────┬───┘ └───┬────┘ └──────┬────────┘
       │         │             │
       └─────────┼─────────────┘
                 │
          ┌──────▼──────┐
          │  cli / ui   │
          └─────────────┘
```

---

## 九、与 v2.0 的关键差异

| 维度 | v2.0 | v3.0 |
|------|------|------|
| 数据流 | 线性单向 | LangGraph 反馈环 |
| LLM 交互 | 手写 prompt + json.loads | LangChain PromptTemplate + OutputParser |
| 可观测性 | print 日志 | LangSmith 全链路 trace |
| 输出形态 | 分析报告（人看） | 可执行脚本 + 测试报告（机器执行） |
| 错误处理 | 标记 TODO | LangGraph 诊断→修复→重测试闭环 |
| 状态管理 | 函数返回值 | TypedDict + checkpointer |
