# DataPilot 项目计划

> **版本**: v3.0 | **更新**: 2026-05-30 | **进度**: 10/10 周 | **测试**: 210

---

## 一、总体分阶段

| 阶段 | 周期 | 目标 | 测试 | 状态 |
|------|------|------|------|------|
| Phase 1 | Week 1-4 | 需求分析助手（概念提取 → 分层检索 → 伪代码） | 81 | ✅ done |
| Phase 2 | Week 5-6 | LangChain 重构 + SQL 生成 + 基础测试 | 136 | ✅ done |
| Phase 3 | Week 7-8 | 逻辑比对 + LangGraph 修复闭环 | 210 | ✅ done |
| Phase 4 | Week 9-10 | LangSmith + Streamlit + Demo | — | ✅ done |

---

## 二、全链路架构

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
  reconciliation/nodes.py  各节点函数（纯函数，可独立测试）
  reconciliation/router.py conditional edges 路由逻辑
```

---

## 三、关键技术决策

| 决策 | 方案 | 理由 |
|------|------|------|
| 线性管道 | 纯 Python/Pydantic | 步骤固定（DM→DWS→ODS 不可绕过），不需 Agent 编排 |
| LLM 交互 | LangChain PromptTemplate + PydanticOutputParser | 集中管理 + 自动校验 + LCEL 链式声明 |
| 修复闭环 | LangGraph StateGraph + conditional edges | 条件路由显式声明 + checkpointer 审计追溯 |
| 脚本生成 | 规则引擎（非 LLM） | 语法确定性，不受 LLM 不稳定影响 |
| 测试代码生成 | **LLM 统一生成** (llm_tester.py) | 表结构+业务逻辑→LLM→完整测试SQL，规则模板做 fallback |
| JOIN 键推断 | 三级：字典外键 → 同名字段 → _id 后缀 | 优先人工标注，降级自动推断 |

### 为什么分层使用框架

```
Layer 3: 修复闭环 → LangGraph StateGraph（图编排是精准场景）
Layer 2: LLM 交互  → LangChain PromptTemplate/OutputParser/Callbacks
Layer 1: 线性管道 → 纯 Python + Pydantic（不需要编排框架）
```

核心理念：**框架用在真正需要的地方，不为关键词硬套**。Agent 框架假设"给目标让 AI 自己规划步骤"，但 DataPilot 的步骤是固定的，本质是 Workflow Engine 而非 Autonomous Agent。

---

## 四、LLM 调用路径

**路径 1: `llm_client.chat_json()` / `chat_text()` — 直接调用（测试 mock 目标）**
适合单一输入输出场景。自带 3 次 retry + JSON 强制。`chat_text()` 用于 SQL 修复等不需结构化输出的场景。

**路径 2: LCEL 链式调用 — LangChain 集成**
```
prompt | llm | parser   (PydanticOutputParser 自动校验)
```
用于概念提取和伪代码生成等需要 PromptTemplate 集中管理的场景。

---

## 五、Phase 1-3 实际产出

### Phase 1: 需求分析助手（81 tests）

| 模块 | 文件 | 说明 |
|------|------|------|
| 数据字典加载 | `dictionary/loader.py` | Excel/CSV → TableInfo (Pandas) |
| 向量索引 | `dictionary/indexer.py` | TableInfo → ChromaDB (BGE embedding) |
| 概念提取 | `extractor/concept.py` | 需求文档 → LLM → BusinessConcept[] |
| 分层检索 | `retrieval/engine.py` | DM→DWS→ODS 递进检索 |
| 语义匹配 | `retrieval/matcher.py` | 精确匹配 + ChromaDB 语义匹配 |
| 伪代码生成 | `generator/pseudocode.py` | 匹配结果 → LLM → PseudoCode |
| CLI | `cli.py` | search / analyze 子命令 |

### Phase 2: LangChain 重构 + SQL 生成（136 tests）

| 新增/改造 | 文件 | 说明 |
|-----------|------|------|
| Prompt 集中管理 | `extractor/prompts.py` | 所有 ChatPromptTemplate 统一管理 |
| LCEL 重构 | `extractor/concept.py` | 手写 prompt → prompt \| llm \| parser |
| LCEL 重构 | `generator/pseudocode.py` | 同上 |
| Callbacks | `callbacks/token_tracker.py` | Token 消耗追踪 |
| Callbacks | `callbacks/audit_logger.py` | LLM 审计日志 |
| SQL 生成 | `generator/script.py` | PseudoCodeStep → SQL 子句映射（规则引擎） |
| LLM Client 增强 | `llm_client.py` | 新增 `get_chat_model()` 导出 |

### Phase 3: 逻辑比对 + LangGraph 修复闭环（210 tests）

| 新增 | 文件 | 说明 |
|------|------|------|
| 统一 LLM 测试生成 | `testing/llm_tester.py` | 表结构+业务逻辑→LLM→完整测试SQL套件 |
| L1 基础质量 | `testing/quality.py` | 主键唯一/空值率/超长/码值 |
| L2 逻辑比对 | `testing/comparison.py` | 原始表聚合 vs 结果表 |
| L3 诊断引擎 | `testing/diagnosis.py` | LLM 五级诊断链路 |
| LangGraph State | `reconciliation/state.py` | ReconciliationState TypedDict |
| LangGraph 节点 | `reconciliation/nodes.py` | run_tests / diagnose / auto_fix / manual_report / retest |
| LangGraph 路由 | `reconciliation/router.py` | after_run_tests / after_diagnose / after_retest |
| LangGraph 图编译 | `reconciliation/graph.py` | StateGraph 组装 + run_reconciliation() 入口 |
| 测试 Mock 模式 | `tests/` | llm_client.chat_json 或 ChatOpenAI.invoke 作为 mock 目标 |

---

## 六、Phase 4: LangSmith + Streamlit + Demo（Week 9-10）

| 任务 | 产出 | 状态 |
|------|------|------|
| LangSmith 全链路 trace 配置 | `.env.example` 环境变量配置，自动 trace | ✅ |
| Streamlit WebUI | `ui/app.py` 三页应用：字典管理 / 需求分析 / 修复闭环 | ✅ |
| 端到端集成测试 | 3 个真实场景 | ⬜ 待续 |
| Demo 场景 + 录制 | 完整操作流程 | ⬜ 待续 |
| README 完善 | 架构图 + Demo 展示 + 面试话术 | ⬜ 待续 |

---

## 七、目录结构（当前）

```
datapilot/
├── config.py                 # HF_ENDPOINT 最顶部 + .env 加载
├── models.py                 # Pydantic 数据模型 + LangGraph State
├── llm_client.py             # chat_json / chat_text / get_chat_model
├── cli.py                    # 命令行入口: search / analyze
├── dictionary/               # loader + indexer (ChromaDB)
├── extractor/                # prompts.py (ChatPromptTemplate 集中管理) + concept.py (LCEL)
├── retrieval/                # engine (DM→DWS→ODS) → matcher → ranker
├── generator/                # pseudocode.py (LLM) + script.py (规则引擎)
├── testing/                  # llm_tester.py (统一LLM) + quality/comparison/diagnosis
├── reconciliation/           # state.py + nodes.py + router.py → graph.py (LangGraph)
├── callbacks/                # token_tracker.py + audit_logger.py
├── demo/                     # data_dict.csv + req_sample.txt
└── tests/                    # 210 tests, pytest
```

---

## 八、测试 Mock 策略

所有测试不调用真实 LLM API。Mock 目标按模块不同：

- **`llm_client.chat_json/chat_text`** — 大部分测试 mock 目标
- **`ChatOpenAI.invoke`** — LCEL 路径测试（concept.py, pseudocode.py）

标准写法：
```python
with mock.patch("llm_client.chat_json", return_value={"concepts": [...]}):
    result = extract_concepts(text)
```

---

## 九、风险与应对

| 风险 | 等级 | 应对 |
|------|------|------|
| LLM 生成 SQL 语法错误 | 高 | SQL 用规则引擎生成，不用 LLM |
| DeepSeek 返回格式不稳定 | 中 | Pydantic 校验 + 3 次 retry |
| BGE 中文语义匹配不准 | 中 | candidates 同义词扩展 + 精确匹配兜底 |
| LLM 生成测试 SQL 不可执行 | 中 | 规则模板 fallback |
| 修复闭环无限循环 | 低 | max_loops=3 + 收敛检测 |

---

## 十、面试技能覆盖

| 技术 | 使用位置 | 面试话术 |
|------|----------|----------|
| **LangGraph** | `reconciliation/graph.py` | "修复闭环不是藏在 if/else 里，是显式的图边声明" |
| **LangChain** | PromptTemplate / OutputParser / LCEL / Callbacks | "手写 prompt 维护成本高，LangChain 统一管理 + schema 自动校验" |
| **ChromaDB** | 数据字典向量库 + metadata filtering | "DM/DWS/ODS 分层检索，metadata 过滤 + BGE 语义匹配" |
| **Pydantic** | 全链路数据契约 + LangGraph State | "类型安全的状态管理，不需要自定义 DSL" |
| **LLM 工程化** | chat_json retry + callbacks | "每次 LLM 调用都有 retry、token 追踪、审计日志" |
