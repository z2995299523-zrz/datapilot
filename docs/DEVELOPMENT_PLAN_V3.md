# DataPilot v3.0 开发计划

> **版本**: v3.0 | **更新**: 2026-05-29 | **目标**: 6 周内完成从需求分析到上线报告的全链路闭环 | **进度**: 5/10 周

---

## 一、总体分阶段

| 阶段 | 周期 | 目标 | 里程碑 | 状态 |
|------|------|------|--------|------|
| Phase 1 | Week 1-4 | 需求分析助手 | 需求 → 伪代码，81 tests | ✅ done |
| Phase 2 | Week 5-6 | LangChain 重构 + 脚本生成 + 基础测试 | 伪代码 → SQL + 主键/空值/超长校验 | 🔄 W5 done, W6 待开始 |
| Phase 3 | Week 7-8 | 逻辑比对 + LangGraph 修复闭环 | 聚合验证 + 诊断 + 自动修复 | ⬜ pending |
| Phase 4 | Week 9-10 | 集成 + LangSmith + Demo | 全链路 + Streamlit + 录制 | ⬜ pending |

---

## 二、各阶段详设

### Phase 2: LangChain 重构 + 脚本生成 + 基础测试（Week 5-6）

| 周 | 任务 | 产出 | 工作量 | 状态 |
|-----|------|------|--------|------|
| W5 | LangChain PromptTemplate + OutputParser 重构 | `extractor/prompts.py` + 改造 `concept.py`/`pseudocode.py` | 1.5 天 | ✅ |
| W5 | Callbacks 模块（TokenTracker + AuditLogger） | `callbacks/` | 0.5 天 | ✅ |
| W5 | SQL 脚本生成引擎 | `generator/script.py` | 1.5 天 | ✅ |
| W6 | 测试规则库 + 第一层质量测试 | `testing/quality.py` + `testing/rules/` | 2 天 | ⬜ |
| W6 | 数据库连接层（抽象 + MySQL/Postgres） | `testing/connection.py` | 1 天 | ⬜ |
| W6 | 测试报告生成 | `testing/report.py` | 1 天 | ⬜ |
| W6 | 测试 + 联调 | 30+ new tests | 1 天 | ⬜ |

**W5 实际产出：**

| 文件 | 说明 | 行数 |
|------|------|------|
| `extractor/prompts.py` | LLM Prompt 集中管理（ChatPromptTemplate） | 125 |
| `extractor/concept.py` | 重构为 LCEL 链式调用 | 35（原 90） |
| `generator/pseudocode.py` | 重构为 LCEL 链式调用 | 83（原 148） |
| `llm_client.py` | 新增 `get_chat_model()` 导出 | +15 |
| `callbacks/token_tracker.py` | Token 消耗追踪 | 75 |
| `callbacks/audit_logger.py` | LLM 审计日志 | 60 |
| `generator/script.py` | SQL 生成引擎 + JOIN 键推断 | 200 |
| `tests/test_script.py` | 脚本生成测试 | 225 |
| `tests/test_concept.py` | 适配 LangChain mock | 重构 |
| `tests/test_pseudocode.py` | 适配 LangChain mock | 重构 |

**v3.0 定位调整：** 去除所有"银行"硬标签，Prompt 改为通用数据开发场景，Demo 数据保留为示例领域之一。

#### W5 详设

**LangChain 重构（1.5 天）— 替换手写 prompt + json.loads**

改动范围：

```
extractor/
├── prompts.py          # (new) 集中管理所有 LLM Prompt
│   ├── EXTRACTION_SYSTEM_PROMPT   → ChatPromptTemplate
│   ├── PSEUDOCODE_SYSTEM_PROMPT   → ChatPromptTemplate
│   └── DIAGNOSIS_SYSTEM_PROMPT    → ChatPromptTemplate (Phase 3 用)
│
├── concept.py          # 改造: concept_prompt | llm | concept_parser
│   └── 移除手写 json.loads + retry，换 LangChain PydanticOutputParser
│
generator/
├── pseudocode.py       # 改造: pseudocode_prompt | llm | pseudocode_parser
│   └── 同上，用 RunnableSequence 组合
```

关键代码模式：

```python
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from langchain.schema.runnable import RunnableLambda

# Prompt 集中管理
concept_prompt = ChatPromptTemplate.from_messages([
    ("system", EXTRACTION_SYSTEM_PROMPT),
    ("human", "需求文档:\n{requirement_text}"),
])

# OutputParser 自动校验 + format_instructions 注入
concept_parser = PydanticOutputParser(pydantic_object=ConceptExtractionResult)

# LCEL 链式声明
extract_chain = concept_prompt | llm | concept_parser

# 全链路: extract → search → pseudocode
analysis_pipeline = extract_chain | RunnableLambda(search_layers) | pseudocode_chain
```

**Callbacks 模块（0.5 天）**

```python
# callbacks/token_tracker.py
class TokenTracker(BaseCallbackHandler):
    """追踪每次 LLM 调用的 Token 消耗 → 成本分析"""
    def on_llm_end(self, response, **kwargs): ...

# callbacks/audit_logger.py
class AuditLogger(BaseCallbackHandler):
    """记录每次 LLM 推理的输入输出 → 审计追溯"""
    pass
```

**`generator/script.py` — SQL 脚本生成（3 天）**

核心逻辑：PseudoCodeStep 中每个字段 → SQL 子句映射

```python
def step_to_sql(step: PseudoCodeStep, tables: dict[str, TableInfo]) -> str:
    """
    PseudoCodeStep → SQL 子句映射：

    1. source_table → FROM {table}
    2. conditions → WHERE {cond1} AND {cond2} ...
    3. joins → LEFT JOIN {right_table} ON {left}.{key} = {right}.{key}
    4. aggregations → GROUP BY + {agg1}, {agg2} ...
    5. output → SELECT {fields}
    """
```

关键能力：

- **JOIN 键推断**：优先数据字典 `relations` 字段（人工标注），其次字段名匹配（两个表都有 `cust_id` → 候选关联键），最后 LLM 辅助推断
- **多层数据源降级**：命中 DM 层直接用；降级到 ODS 层自动加 GROUP BY 补齐到等效粒度
- **码值替换**：伪代码中 `cust_status = '01' (活跃)` → SQL 中 `WHERE cust_status = '01'`，注释保留 `-- 活跃`
- **模板兜底**：LLM 生成 + Jinja2 语法校验，保证输出合法 SQL

SQL 优先而不是 Python (pandas) 的原因：

- SQL 是数据库原生语言，执行计划可分析
- 测试引擎直接运行验证 SQL
- 数据血缘可追踪（FROM → JOIN → WHERE → GROUP BY）

#### W6 详设

**`testing/quality.py` — 第一层：基础数据质量**

元数据驱动，零 LLM 调用：

```
输入: 脚本执行后的结果表 + 数据字典（表结构定义）
输出: QualityReport（每个检查项 pass/fail + 详情）
```

| 检查项 | 实现 | 规则来源 |
|--------|------|----------|
| 主键唯一性 | `SELECT pk, COUNT(*) FROM result GROUP BY pk HAVING COUNT(*) > 1` | 数据字典 `is_primary_key` |
| 主键非空 | `SELECT COUNT(*) FROM result WHERE pk IS NULL` | 同上 |
| 空值率 | 对每个字段: `SUM(CASE WHEN col IS NULL THEN 1 ELSE 0 END) / COUNT(*)` | 数据字典（主键 0%，其他可配置阈值） |
| 字段超长 | 对每个 varchar(N): `MAX(LENGTH(col))` 对比 N*2 | 数据字典 `column_type` |
| 码值合法性 | `SELECT DISTINCT col FROM result WHERE col NOT IN ('01','02','03')` | 数据字典 `code_values` |
| 行数合理性 | `SELECT COUNT(*)` > 0 且 < 设定上限 | 规则库预设 |

不需要连接原始表——只读结果表。和 ETL 中的 "技术性校验" 完全对齐。

**`testing/connection.py` — 数据库连接层**

抽象出统一接口，支持多种数据库：

```python
class DBConnection(ABC):
    def execute(self, sql: str) -> pd.DataFrame: ...
    def table_exists(self, table_name: str) -> bool: ...
    def get_row_count(self, table_name: str) -> int: ...

class MySQLConnection(DBConnection): ...
class PostgresConnection(DBConnection): ...
class HiveConnection(DBConnection): ...  # 金融/电信等行业常用
```

**`testing/report.py` — 测试报告**

结构化输出 + Markdown 渲染：

```
测试摘要
├── 基础质量: 6/8 通过, 2 失败
│   ├── ✅ 主键唯一性: dm_customer_active.cust_id
│   ├── ❌ 空值率: dm_customer_active.last_trans_date (12.3% > 5% 阈值)
│   └── ⚠ 码值异常: channel_type 出现未定义的 '05'
├── 逻辑比对: (Phase 3 实现)
└── 诊断建议:
    ├── last_trans_date 空值可能来自 LEFT JOIN 左表无匹配
    └── channel_type='05' 请确认数据字典是否需要补充码值定义
```

### Phase 3: 逻辑比对 + LangGraph 修复闭环（Week 7-8）

| 周 | 任务 | 产出 | 工作量 |
|-----|------|------|--------|
| W7 | 第二层：逻辑结果比对 | `testing/comparison.py` | 2 天 |
| W7 | 反向验证 SQL 生成 | `testing/comparison.py` | 1 天 |
| W7 | 第三层：诊断引擎（LangChain prompt） | `testing/diagnosis.py` | 2 天 |
| W8 | LangGraph StateGraph 定义 + 编译 | `reconciliation/graph.py` | 1.5 天 |
| W8 | LangGraph 节点函数 + 路由 | `reconciliation/nodes.py` + `router.py` | 1.5 天 |
| W8 | 修复闭环联调 + 测试 | `reconciliation/report.py` + 20+ tests | 2 天 |

#### W7 详设

**`testing/comparison.py` — 第二层：逻辑比对**

从伪代码步骤中反向推导验证 SQL：

```python
def derive_verify_sql(step: PseudoCodeStep, source_tables: list[str]) -> str:
    """
    伪代码: "按渠道统计活跃客户数，聚合 COUNT(DISTINCT cust_id)"
    反向推导: 取原始表 (ODS transaction_log / DWS cust_behavior)
             按 channel_type GROUP BY
             COUNT(DISTINCT cust_id)
             与结果表逐行对比
    """
```

验证策略：

| 聚合类型 | 验证方法 |
|----------|----------|
| COUNT | 原始表 COUNT(*) vs 结果表 SUM(count_column) |
| COUNT DISTINCT | 原始表 COUNT(DISTINCT x) vs 结果表值 |
| SUM | 原始表 SUM(x) vs 结果表 SUM(x) |
| AVG | SUM/COUNT 拆开各自比对 |
| MAX/MIN | 原始表取极值，验证在结果表值域内 |

关键设计：验证 SQL 在**原始明细表**上执行（ODS/DWS 层的表），拿聚合结果与脚本在 DM 层生成的汇总结果比对。如果原始表和结果表数字对不上 → 脚本逻辑有问题。

**`testing/diagnosis.py` — 第三层：诊断引擎**

当第一/二层发现异常时触发。使用 LangChain PromptTemplate + PydanticOutputParser：

```python
diagnosis_prompt = ChatPromptTemplate.from_messages([
    ("system", DIAGNOSIS_SYSTEM_PROMPT),
    ("human", "测试异常:\n{failures}\n\n上下文:\n{context}"),
])
diagnosis_parser = PydanticOutputParser(pydantic_object=DiagnosisResult)
diagnosis_chain = diagnosis_prompt | llm | diagnosis_parser
```

诊断链路（按顺序逐级排查）：

```
Level 1: 数据源检查
  → 结果表对应的原始表有数据吗？时间范围对吗？

Level 2: 码值映射检查
  → 结果表中的码值是否都在数据字典定义的合法值范围内？
  → 码值格式是否一致？('01' vs '1' vs ' 01')

Level 3: JOIN 逻辑检查
  → JOIN 键的类型是否一致？(varchar vs int)
  → LEFT JOIN 是否导致右表字段大面积 NULL？
  → JOIN 条件是否遗漏了必要字段？

Level 4: 业务口径检查
  → "活跃客户" 的定义在伪代码中是否完整？
  → 需求文档中的隐含条件是否被遗漏？

Level 5: 概念遗漏检查
  → 需求中的概念是否在检索阶段就未匹配？
  → 数据字典是否缺少对应的表/字段？
```

每一级诊断都是一个独立的分析函数，输出 `DiagnosisResult`:

```python
class DiagnosisResult(BaseModel):
    level: int                     # 诊断层级
    root_cause: str                # 根因分类
    confidence: float              # 置信度
    evidence: list[str]            # 证据链
    fixable_automatically: bool    # 是否可自动修复
    suggested_fix: str             # 修复建议
```

#### W8 详设

**`reconciliation/graph.py` — LangGraph StateGraph（核心亮点）**

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from typing import TypedDict

class ReconciliationState(TypedDict):
    """修复闭环的状态 Schema"""
    script_sql: str
    test_results: list[TestResult]
    diagnosis: DiagnosisResult | None
    fix_history: list[str]
    retry_count: int
    final_report: Report | None

def build_reconciliation_graph() -> StateGraph:
    graph = StateGraph(ReconciliationState)

    graph.add_node("run_tests", run_all_tests)
    graph.add_node("diagnose", diagnose_failures)
    graph.add_node("auto_fix", apply_automatic_fix)
    graph.add_node("human_review", generate_review_report)

    graph.set_entry_point("run_tests")

    # conditional edges: LangGraph 的核心价值
    graph.add_conditional_edges(
        "run_tests",
        route_by_test_result,
        {"pass": END, "fail": "diagnose"},
    )

    graph.add_conditional_edges(
        "diagnose",
        route_by_fixability,
        {"auto": "auto_fix", "manual": "human_review"},
    )

    graph.add_edge("auto_fix", "run_tests")  # 闭环！
    graph.add_edge("human_review", END)

    return graph.compile(checkpointer=MemorySaver())
```

**`reconciliation/nodes.py` — 节点函数**

每个节点是独立的纯函数，可单独测试：

| 节点 | 职责 |
|------|------|
| `run_all_tests` | 执行三层测试，返回 `TestResult` 列表 |
| `diagnose_failures` | 调诊断引擎，返回 `DiagnosisResult` |
| `apply_automatic_fix` | 码值替换/CAST转换/补充条件 → 重生成脚本 |
| `generate_review_report` | 生成人工确认报告（证据链 + 建议方案） |

**`reconciliation/router.py` — 条件路由**

```python
def route_by_test_result(state: ReconciliationState) -> str:
    """全部通过 → pass，任何失败 → fail"""
    if all(t.passed for t in state["test_results"]):
        return "pass"
    return "fail"

def route_by_fixability(state: ReconciliationState) -> str:
    """可自动 → auto，不可自动 → manual"""
    if state["diagnosis"].fixable_automatically:
        return "auto"
    return "manual"
```

**闭环终止条件：**

- 所有测试项通过（pass）
- 或剩余异常经诊断后确认 "无法自动修复"，且已生成人工确认报告
- 最大循环次数限制（防止无限重试，默认 3 次）

### Phase 4: 集成 + LangSmith + Demo（Week 9-10）

| 周 | 任务 | 产出 |
|-----|------|------|
| W9 | LangSmith 全链路 trace 配置 | 环境配置 + trace dashboard |
| W9 | CLI 完善（全链路命令） + Streamlit 升级 | `cli.py` + `ui/app.py` |
| W9 | 端到端集成测试（3 个真实场景） | 集成测试 |
| W10 | Demo 场景构建 + 录制 + README | 完整 Demo |

**LangSmith 集成（W9）**

```bash
# 环境变量配置即可，无需侵入业务代码
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...
LANGCHAIN_PROJECT=datapilot
```

每次 LLM 调用自动 trace 到 LangSmith：
- 概念提取 → token 消耗 + 输入输出
- 伪代码生成 → token 消耗 + Pydantic 校验结果
- 诊断推理 → 根因 + 置信度 + 决策路径

面试展示：打开 LangSmith 网页，展示全链路 Trace 树状图。

---

## 三、全链路命令

```
# 完整链路（单次）
python cli.py run \
  --req demo/req_sample.txt \
  --dict demo/data_dict.csv \
  --db mysql://user:pass@host:3306/db \
  --output report.md

# 带修复闭环（LangGraph 自动重试）
python cli.py run \
  --req demo/req_sample.txt \
  --dict demo/data_dict.csv \
  --db mysql://... \
  --auto-fix \
  --max-retry 3

# 仅测试（已有脚本，只跑测试）
python cli.py test \
  --script output/analysis.sql \
  --dict demo/data_dict.csv \
  --db mysql://... \
  --target-table result_table
```

---

## 四、技术决策汇总

| 决策 | 选项 | 结论 | 理由 |
|------|------|------|------|
| 底层框架 | HermesAgent / OpenClaw / 纯 Python | **纯 Python + LangGraph 分层** | 线性 Pipeline 用纯 Python/Pydantic；修复闭环用 LangGraph StateGraph |
| LLM 交互 | 手写 prompt + json.loads / LangChain | **LangChain PromptTemplate + OutputParser** | 结构化 prompt 管理 + 自动 schema 校验 + LCEL 链式声明 |
| 脚本生成 | LLM 自由生成 / 模板 + LLM 填充 | **模板约束 + LLM 填充** | 保证语法正确，LLM 只填变量 |
| SQL vs Pandas | SQL / Pandas | **SQL** | 数据库原生、执行计划可分析、测试可直接运行 |
| 修复闭环 | 纯 Python if/else / LangGraph | **LangGraph StateGraph** | 条件路由显式声明为图边 + checkpointer 持久化 + streaming 实时输出 |
| 状态管理 | 函数返回值 / LangGraph State | **TypedDict + checkpointer** | 类型安全 + 审计回溯 |
| 可观测性 | print 日志 / LangSmith | **LangSmith** | 全链路 LLM trace + 可视化 dashboard |
| 数据库连接 | 每种数据库写适配 / SQLAlchemy | **抽象 DBConnection + 按需实现** | 先支持 MySQL/Postgres，Hive 按需加 |
| 测试报告 | 纯文本 / Markdown / JSON | **JSON + Markdown 渲染** | JSON 可对接 CI/CD，Markdown 给人看 |

---

## 五、面试技能覆盖

| 技术 | DataPilot 中的使用 | 面试话术 |
|------|-------------------|----------|
| **LangGraph** | `reconciliation/graph.py` — StateGraph + conditional edges + checkpointer | "修复闭环不是藏在 if/else 里，是显式的图边声明" |
| **LangChain** | PromptTemplate / PydanticOutputParser / LCEL / Callbacks | "手写 prompt 维护成本高，LangChain 统一管理 + schema 自动校验" |
| **LangSmith** | 全链路 LLM trace | "每次 LLM 调用自动 trace，甲方审计时一目了然" |
| **ChromaDB** | 数据字典向量库 + metadata filtering | "DM/DWS/ODS 分层检索，metadata 过滤 + BGE 语义匹配" |
| **Pydantic** | 全链路数据契约 + LangGraph State Schema | "类型安全的状态管理，不需要自定义 DSL" |
| **HermesAgent/OpenClaw** | 框架选型评估文档 | "评估了 2 个 Agent 框架，确定不适合后选择 LangGraph 分层方案" |

---

## 六、测试策略

| 层级 | 测试类型 | 目标数量 | Mock 策略 |
|------|----------|----------|-----------|
| 单元测试 | 每个模块的函数 | 80+ | LLM 调用 mock，DB 用 SQLite 内存库 |
| LangGraph 节点测试 | 每个节点的纯函数 | 10+ | State 输入/输出，不跑完整 graph |
| 集成测试 | 多模块联调 | 20+ | 用 demo 数据字典 |
| 端到端 | 全链路 3 个真实场景 | 3 | 连接真实数据库（测试库） |

总计 v3.0 期望测试数：**101 (当前) → 160+ (v3.0 完成)**

---

## 七、风险

| 风险 | 等级 | 应对 |
|------|------|------|
| LLM 生成的 SQL 语法错误 | 高 | Jinja2 模板约束 + 数据库语法校验（EXPLAIN） |
| 不同数据库 SQL 方言差异 | 中 | 抽象 SQL 方言层，先支持 MySQL/PostgreSQL |
| 诊断引擎误判根因 | 中 | 置信度机制 + 人工确认环节 |
| LangGraph learning curve | 低 | 仅用 StateGraph + conditional edges + checkpointer，不涉及高级特性 |
| 原始表不可访问（权限） | 低 | 降级策略：用结果表自身的统计一致性测试 |
| 修复闭环无限循环 | 低 | 最大重试 3 次 + 收敛检测 |

---

## 八、依赖

```
Week 5-6 依赖: Week 1-4 (v2.0 完成) ✅
Week 7-8 依赖: Week 5-6 (LangChain 重构 + 脚本生成 + 基础测试)
Week 9-10 依赖: Week 7-8 (LangGraph 闭环 + 逻辑比对 + 诊断)

关键路径:
  LangChain 重构 → generator/script.py → testing/quality.py
  → testing/comparison.py → testing/diagnosis.py
  → reconciliation/graph.py (LangGraph StateGraph)
```

## 九、总时间线

```
Week 1-4  [done]  Phase 1: 需求分析助手（纯 Python + ChromaDB）
Week 5  [done]    LangChain 重构 + Callbacks + SQL 生成引擎
Week 6  [todo]    基础数据质量测试 + 数据库连接层 + 测试报告
Week 7  [todo]    逻辑比对 + 诊断引擎
Week 8  [todo]    LangGraph 修复闭环
Week 9  [todo]    LangSmith + CLI + 集成测试
Week 10 [todo]    Streamlit + Demo + README
─────────────────────────────────────────────────────────
总计 10 周，当前进度: 5/10 周完成，101 tests
```
