# DataPilot v3.1 优化 Spec — 从 Pipeline 到 Agent 架构

> 创建: Hermes Agent 分析 v3.0 代码，张润泽讨论优化方向
> 执行: Claude Code
> 约束: 必须读 `agentflow-dev` + `datapilot-dev` skill 后编码
> 原则: 保留深度 + 加容错，不砍功能保稳定

---

## 当前架构概览

```
需求.txt → 概念提取(LLM) → 分层检索(ChromaDB) → 伪代码(LLM) → SQL(规则引擎)
                                                      ↓
                                             L1质量测试 + L2比对测试
                                                      ↓ 失败
                                             诊断(LLM) → 自动修复 → 重测
```

47 个 .py 文件, 210 tests, 全链路串行同步执行。

---

## P1: Layer 1 核心壁垒 — 需求→数据断言翻译

### 问题

当前流程能匹配到 `cust_status` 列和码值 `{01: 活跃, 02: 休眠, 03: 销户}`，但**码值从未被翻译成 SQL WHERE 条件**。LLM 伪代码里写了"筛选活跃客户"，但规则引擎不知道"活跃"= `cust_status='01'`。

### 目标

在检索和伪代码之间插入 **断言翻译步骤**，把"概念+码值"翻译成可执行的 SQL 条件。

### 输入→输出

```
输入:
  concepts: [BusinessConcept(concept="活跃客户", type=ENTITY)]
  retrieval: RetrievalResult(matches=[TableMatch(table="customer", columns=[
      ColumnMatch(name="cust_status", code_values=[{01: 活跃}, {02: 休眠}])
  ])])

输出:
  assertions: [
    CodeAssertion(column="cust_status", operator="=", value="01", concept="活跃客户"),
    TimeAssertion(column="trade_date", operator=">=", value="DATE_SUB(NOW(), INTERVAL 6 MONTH)"),
    AggregationAssertion(column="txn_amt", function="SUM"),
  ]
```

### 实现

1. **新文件 `extractor/assert.py`**: `build_assertions(concepts, retrieval) -> list[Assertion]`
   - 遍历每个概念，找匹配到的列
   - 如果列有码值且概念名与某个码值的 meaning 匹配 → CodeAssertion
   - 如果概念类型是 TIME_RANGE → TimeAssertion（解析"近6个月""今年以来"等）
   - 如果概念类型是 METRIC + 聚合关键字 → AggregationAssertion

2. **新模型 `models.py`**: 增加 `Assertion` 类型：
   ```python
   class AssertionType(str, Enum):
       CODE_FILTER = "code_filter"
       TIME_RANGE = "time_range"
       AGGREGATION = "aggregation"
       NOT_NULL = "not_null"

   class Assertion(BaseModel):
       type: AssertionType
       column: str
       operator: str = "="
       value: str = ""
       concept_source: str = ""
       confidence: float = 1.0  # P2 用：低置信度时传给 Generator 二次确认
   ```

3. **改 `cli.py` cmd_analyze**: 在步骤 2（检索）和步骤 3（伪代码）之间插入：
   ```
   步骤 2.5: 构建数据断言...
   assertions = build_assertions(extraction.concepts, result)
   ```

4. **改 `generator/pseudocode.py` generate()**: 接收 assertions 参数，在 prompt 中注入"已确定的 SQL 条件"，避免 LLM 自己猜。

5. **改 `generator/script.py`**: WHERE 条件生成时优先使用 Assertion。

### 测试 (3-5 个)

- 码值匹配: "活跃客户" + `{01: 活跃}` → `cust_status='01'`
- 时间范围: "近6个月" → `trade_date >= DATE_SUB(NOW(), INTERVAL 6 MONTH)`
- 未匹配: 概念无对应码值时 fallback 为 `ColumnAssertion(column="cust_status", operator="IS NOT NULL")`
- 聚合: "交易金额" → `SUM(txn_amt)`

### 面试话术

> "DataPilot 的核心壁垒在 Layer 1——业务语言到数据条件的翻译。一般工具只做表匹配，我能把'活跃客户'翻译成 `cust_status='01' AND 近6月有交易`。这是银行 ETL 最痛的点——业务说的'正常'和数据库里的 01/02/03 之间的鸿沟。"

---

## P2: 3 Agent 架构 — 合并后的 Agent 体系

### 为什么不是 8 Agent？

8 Agent 串联有两个硬伤：

**1. 容错太低。** 每个 Agent 依赖 LLM 调用，假设单步成功率 95%，8 步串行整体只有 66%。链太长，任何一步失败都会丢失上下文。

**2. 划分粒度错了。** 有些"Agent"本质上不是 Agent——它们没有自己的决策循环，只是工具。

| 原 Spec Agent | 本质 | 应该归类为 |
|--------------|------|-----------|
| Supervisor | 需要决策循环（理解→分解→分配） | ✅ Agent |
| KnowledgeRetrieval | 一次查询（查 schema 元数据） | ❌ 工具 |
| Parse Agent | 需要三阶段解析（sqlparse→LLM→DAG） | ✅ Agent（v1 用不上，v2 做） |
| Assert Agent | 确定性映射（码值→SQL条件） | ❌ 工具 |
| Gen Agent | 需要自校验循环（生成→校验→修复） | ✅ Agent |
| Exec Agent | 纯执行（安全检查+跑 SQL） | ❌ 工具 |
| Analyze Agent | 需要诊断循环（失败→根因→重试） | ✅ Agent |
| Report Agent | 数据拼接（格式化 Markdown） | ❌ 工具 |

**合并结果：3 个真正的 Agent，其余退化为工具。**

### 新架构

```
┌─────────────────────────────────────────────────────────┐
│                   Supervisor Agent                       │
│                                                         │
│  职责: 理解需求 → 查数据模型 → 翻译成条件 → 分配任务        │
│                                                         │
│  内部工具:                                               │
│    schema_query()     — 查 information_schema            │
│    vector_match()     — 向量语义补充匹配（P3）             │
│    code_translate()   — 码值→SQL条件（P1 的 assert.py）   │
│                                                         │
│  容错:                                                   │
│    LLM 意图分析失败 → 降级: 关键词规则匹配                  │
│    schema 查询失败   → fallback: 用缓存数据字典             │
│    码值翻译失败      → 标记低置信度，传给 Generator 确认     │
│                                                         │
│  输出: assertions + confidence_scores + context          │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   Generator Agent                        │
│                                                         │
│  职责: 选策略 → 生成SQL → 自校验 → 修复 → 执行             │
│                                                         │
│  内部工具:                                               │
│    syntax_validate()  — SQL 语法校验                     │
│    exec_check()       — 在安全沙箱中执行并收集结果         │
│    sql_security()     — DROP/DELETE 拦截                 │
│                                                         │
│  容错:                                                   │
│    生成→校验→不通过→LLM 自修复（最多 3 轮）                │
│    LLM 修复失败 → 正则 fallback                           │
│    正则也失败 → 标记为 manual_fix                         │
│                                                         │
│  输出: validated_sql + execution_results                 │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   Diagnoser Agent                        │
│                                                         │
│  职责: 运行测试 → 诊断失败 → 分类根因 → 决定修复策略        │
│                                                         │
│  内部工具:                                               │
│    run_test()         — L1质量 + L2比对                  │
│    diff_compare()     — 新旧数据差异对比                  │
│    classify_error()   — 7种差异分类                      │
│    generate_report()  — 汇总 Markdown 报告               │
│                                                         │
│  容错:                                                   │
│    语法错误 → auto_fix → 回到 Generator                   │
│    语义错误 (表选错/JOIN错) → 回到 Supervisor              │
│    无法自动修复 → manual_report → END                     │
│    循环 ≤ 3 次                                           │
│                                                         │
│  输出: 最终报告 (通过 / 人工介入)                          │
└─────────────────────────────────────────────────────────┘
```

### 3 Agent vs 8 Agent 对比

| | 原 8 Agent | 新 3 Agent |
|---|---|---|
| 串行失败率 (95%/步) | 0.95^8 ≈ 66% | 0.95^3 ≈ 86% |
| LLM 调用次数 | 4-5 次 | 2-3 次 |
| 序列化边界 | 7 个（数据在 Agent 间反复序列化） | 2 个 |
| 内部重试循环 | 分散在各 Agent | 集中在 Agent 内部 |
| 面试能讲清吗 | 能但需要 5 分钟 | "三个角色各司其职"一句话 |

### 当前模块 → 3 Agent 映射

| 当前代码 | 归属 Agent | 角色 |
|---------|-----------|------|
| `extractor/concept.py` | **Supervisor** | 概念提取（LLM 意图分析） |
| `retrieval/engine.py` | **Supervisor** | 工具：分层检索 |
| 新增 `retrieval/schema_reader.py` | **Supervisor** | 工具：information_schema 直读 |
| 新增 `retrieval/vector_match.py` | **Supervisor** | 工具：向量语义补充匹配（P3） |
| 新增 `extractor/assert.py` | **Supervisor** | 工具：码值→条件翻译 |
| `generator/pseudocode.py` | **Generator** | 伪代码生成 |
| `generator/script.py` | **Generator** | SQL 规则引擎生成 |
| 新增 `generator/security.py` | **Generator** | 工具：SQL 安全检查 |
| `testing/quality.py` | **Diagnoser** | 工具：L1 基础质量 |
| `testing/comparison.py` | **Diagnoser** | 工具：L2 逻辑比对 |
| `testing/diagnosis.py` | **Diagnoser** | 诊断引擎 |
| `reconciliation/graph.py` | **Diagnoser** | LangGraph 修复闭环 |
| `reconciliation/nodes.py` | **Diagnoser** | 修复节点函数 |
| `reconciliation/router.py` | **Diagnoser** | conditional edges |

### 实现策略

**分两阶段，不改核心逻辑，只改编排层：**

**阶段 A (P1 完成后):** 新增 `datapilot/graph.py` — 用 LangGraph StateGraph 串联 3 个 Agent：

```python
# graph.py — 3 Agent 编排
workflow = StateGraph(AgentState)
workflow.add_node("supervisor", supervisor_node)  # 封装现有 Pipeline 前半段
workflow.add_node("generator", generator_node)    # 封装现有 Pipeline 后半段
workflow.add_node("diagnoser", diagnoser_node)    # 封装现有修复闭环

workflow.set_entry_point("supervisor")
workflow.add_edge("supervisor", "generator")
workflow.add_edge("generator", "diagnoser")
workflow.add_conditional_edges("diagnoser", after_diagnose, {
    "end": END,
    "retry_generate": "generator",
    "retry_all": "supervisor",  # 语义错误 → 重新理解需求
})
```

每个 node 内部封装现有模块，加 try/except 容错和降级路径。

**阶段 B:** 在 `cli.py` 中新增 `agent` 子命令，与现有 `analyze` 并行存在：
```
python cli.py agent --req demo/req_sample.txt    # 3 Agent 模式
python cli.py analyze --req demo/req_sample.txt  # 原 Pipeline（兼容）
```

### 面试话术

> "我设计了 3 个协作 Agent，而不是 8 个。Supervisor 负责理解业务需求——它能把'活跃客户'翻译成 `cust_status='01'`，查数据库元数据，用向量检索做语义补充。Generator 负责生成 SQL 并自校验——生成后自己跑语法检查和沙箱执行，不通过就自动修复。Diagnoser 负责诊断和决策——它不只修语法错误，还能判断'是不是表选错了'，如果是就回退给 Supervisor 重新分析。
>
> 为什么不是 8 个？因为 8 个串行 Agent 的成功率太低——假设每个 95%，8 个串联只剩 66%。而且有些所谓 Agent 本质上只是工具。我把工具退化为 Agent 内部的函数调用，只保留 3 个真正需要独立决策循环的 Agent，整体成功率提到 86%。"

---

## P3: 混合检索 — information_schema 直读 + 向量语义补充

### 问题

v1 Spec 决策是不引入 RAG，用 `information_schema` 直读。当前代码用了 ChromaDB + BGE embedding。

但纯精确匹配有一个盲区：**业务术语和数据库字段名不是一一对应的。**

```
"活跃客户" ↔ cust_status='01'     → 码值能处理 ✓
"交易对手方" ↔ counterparty_id    → 字段名不包含"对手方"，精确匹配失败 ✗
"资金流向" ↔ fund_direction       → 业务人员说"流向"，技术字段叫 direction ✗
```

所以需要混合策略：**主路径用 information_schema 精确匹配，向量检索做语义兜底。**

### 目标

两级匹配机制：

```
第一级: information_schema 精确匹配
  - 字段名 = 概念候选词 → 直接命中 (confidence=1.0)
  - 字段注释包含概念关键词 → 直接命中 (confidence=0.9)
  
第二级: BGE 向量语义匹配（仅在第一级失败时触发）
  - 把概念文本向量化 → 在 schema 向量库中搜 top-3
  - 命中 → 标记 confidence=0.6~0.8（低于精确匹配）
  - 未命中 → 标记 unmatched
  
低 confidence 的匹配 → 传给 Supervisor 的 LLM 二次确认
```

### 实现

1. 新增 `retrieval/schema_reader.py`:
   ```python
   def read_schema(conn, schema_name: str) -> DataDictionary
   ```
   直接读 `information_schema.columns` + `information_schema.tables`，构建 `DataDictionary`。

2. 新增 `retrieval/vector_match.py`:
   ```python
   def vector_backup_match(concept: BusinessConcept, collection: ChromaDB.Collection) -> list[TableMatch]
   ```
   只在精确匹配失败时调用。保留现有的 BGE + ChromaDB 代码，重新定位为"语义兜底"。

3. 改 `retrieval/engine.py` 的 `search()`:
   ```python
   def search(concepts, collection, conn=None):
       for concept in concepts:
           match = exact_match(concept, schema_dict)      # 第一级: information_schema
           if not match:
               match = vector_backup_match(concept, ...)  # 第二级: 向量兜底
           if match:
               match.confidence = 1.0 if exact else 0.7   # 标记置信度
   ```

4. ChromaDB 保留，但注释改为 `# 语义兜底: 当 information_schema 精确匹配失败时使用`

### 面试话术

> "我的检索策略是两级的。第一级用 information_schema 直读元数据——字段名、注释、码值全拿到，做精确匹配。这是最快的，零额外依赖。但业务术语不是百分百能对上数据库字段名——比如业务说'交易对手方'，数据库字段叫 counterparty_id。这时候第二级向量语义匹配接管——用 BGE 中文 embedding 找到语义最接近的字段。两级互补，既快又准。"

---

## P4: 修复闭环的语义打通

### 问题

当前修复闭环只能做**语法**修复（加 COALESCE、加 DISTINCT、截断超长字段）。不能做**语义**修复——比如"表选错了，应该用另一张表"。

### 目标

Diagnoser Agent 的诊断结果能够区分：

- `fix_level="syntax"` → 回到 Generator Agent 自动修复
- `fix_level="semantic"` → 回到 Supervisor Agent 重新分析

### 实现

在 `ReconciliationState` 中加字段：
```python
fix_level: str  # "syntax" | "semantic" | "manual"
```

在 diagnose_node 中加判断：
- 失败模式是"空值率过高 + 码值不在合法范围" → 可能是表选错了 → `fix_level="semantic"`
- 失败模式是"主键唯一性失败但数据来源字段不同" → 可能是 JOIN 条件错了 → `fix_level="semantic"`
- 语法类错误（字段缺失、超长、重复） → `fix_level="syntax"`

在 `graph.py` 的 conditional_edge 中：
```python
if fix_level == "semantic":
    return "retry_all"  # 回到 Supervisor
elif fix_level == "syntax":
    return "retry_generate"  # 回到 Generator
else:
    return "end"  # 人工介入报告
```

---

## P5: 预期结果比对测试 — 用户上传数据集，自动对照纠错

### 问题

当前测试只有 L1（质量检查）和 L2（与源表聚合比对），缺少最关键的一环：**用户手里往往有已知正确的结果数据**。比如：

```
需求: "统计2025年各分行活跃客户的交易金额"
已知: 用户从旧系统导出了一份 CSV，里面有 12 行的正确结果
  
当前流程:
  生成 SQL → 执行 → L1检查 (null/重复) ✓
                  → L2检查 (与源表聚合) ✓
                  → 看起来都通过了
                  → 但分行3的金额和用户预期差了 30% ← 发现不了！

如果有预期数据集:
  生成 SQL → 执行 → 与预期 CSV 逐行比对 → 分行3金额偏差 30%
                  → 差异注入 LLM 上下文
                  → "分行3的差异可能是 JOIN 条件漏了 org_type 过滤"
                  → LLM 精准修复 SQL → 重新比对 → 通过
```

### 目标

新增 **L2.5: 预期结果比对测试**。用户上传预期数据集（CSV/JSON/数据库表），系统将生成 SQL 的执行结果与预期数据做**逐行逐列的差异分析**，差异报告作为 Diagnoser Agent 的输入，帮助 LLM 理解"不是语法错了，是逻辑偏了"。

### 输入→输出

```
输入:
  - actual_results: SQL 执行结果 (DataFrame)
  - expected_dataset: 用户上传的 CSV 文件路径 (或表名)
  - key_columns: ["branch_id", "year_month"]  ← 对齐键
  - compare_columns: ["txn_amount", "txn_count"]  ← 比对列
  - tolerance: {"txn_amount": 0.01, "txn_count": 0}  ← 允许偏差

输出:
  - ExpectedComparisonReport:
      match_count: 10
      mismatch_count: 2
      missing_in_actual: []     # 预期有、实际没有的行
      extra_in_actual: ["分行13"]  # 实际有、预期没有的行
      value_diffs: [
        {key: "分行3", column: "txn_amount", expected: 500000.00,
         actual: 350000.00, diff_pct: 0.30},
      ]
      summary: "12个分行中10个完全匹配，分行3交易金额偏差30%，实际多出1个分行"
```

### 实现

1. **新文件 `testing/expected_compare.py`**:
   ```python
   def compare_with_expected(
       actual_df: pd.DataFrame,
       expected_path: str,  # CSV 路径 或 表名
       key_columns: list[str],
       compare_columns: list[str],
       tolerance: dict[str, float] | None = None,
   ) -> ExpectedComparisonReport
   ```
   
   核心逻辑：
   ```python
   # 1. 加载预期数据
   expected_df = load_expected_dataset(expected_path)
   
   # 2. 按键列对齐
   merged = actual_df.merge(expected_df, on=key_columns, 
                            how="outer", suffixes=("_actual", "_expected"),
                            indicator=True)
   
   # 3. 分类差异
   missing = merged[merged["_merge"] == "right_only"]     # 预期有，实际没
   extra = merged[merged["_merge"] == "left_only"]        # 实际有，预期没
   matched = merged[merged["_merge"] == "both"]           # 都有的行
   
   # 4. 对匹配行做逐列偏差分析
   for col in compare_columns:
       diff = (matched[f"{col}_actual"] - matched[f"{col}_expected"]).abs()
       diff_pct = diff / matched[f"{col}_expected"].abs()
       tolerance_val = tolerance.get(col, 0.01) if tolerance else 0.01
       outliers = matched[diff_pct > tolerance_val]
       # → 记录偏差行 + 偏差比例
   ```

2. **新模型 `models.py`**: 增加 `ExpectedComparisonReport`：
   ```python
   class ValueDiff(BaseModel):
       key_values: dict           # {"branch_id": "分行3"}
       column: str                # "txn_amount"
       expected_value: float
       actual_value: float
       diff_absolute: float
       diff_percent: float

   class ExpectedComparisonReport(BaseModel):
       total_expected: int
       total_actual: int
       match_count: int
       mismatch_count: int
       missing_in_actual: list[dict]   # 漏掉的行
       extra_in_actual: list[dict]     # 多出的行
       value_diffs: list[ValueDiff]    # 数值偏差
       summary: str
       overall_passed: bool  # mismatch_count == 0 and len(value_diffs) == 0
   ```

3. **改 `generator/script.py`**: 支持可选参数 `expected_dataset_path`，当用户提供了预期数据时，在生成 SQL 后自动跑比对。

4. **改 `cli.py`**: 新增 `--expected` 参数：
   ```
   python cli.py analyze --req demo/req_sample.txt --expected demo/expected_result.csv
   ```

5. **改 Diagnoser Agent 的诊断 prompt**: 当有 `ExpectedComparisonReport` 时，差异详情注入 LLM 上下文。Prompt 中增加：

   ```
   以下是你的 SQL 执行结果与用户提供的预期数据集的差异：
   - 分行3: txn_amount 实际=350000, 预期=500000, 偏差=30%
   - 分行7: txn_count 实际=45, 预期=67, 偏差=33%
   - 实际结果多出了"分行13"，预期数据中没有
   
   请分析这些差异的可能根因，并修复 SQL 逻辑（不是语法）：
   - 偏差集中在特定分行 → 是否 WHERE 条件中的 org_type 过滤错了？
   - 多出了分行 → 是否 JOIN 条件导致数据膨胀？
   - 少了一行 → 是否某个 LEFT JOIN 应该用 INNER JOIN？
   ```

### 与现有测试层的关系

```
L1 质量测试:         SQL → 查 null/重复/超长/码值         → 语法层
L2 逻辑比对:         SQL → 与源表聚合值对比               → 聚合层
L2.5 预期结果比对:   SQL → 与用户提供的正确结果逐行对比    → 语义层 ← 新增
L3 诊断引擎:         汇总 L1+L2+L2.5 → 根因分析 → 修复策略
```

**L2.5 的价值不是"发现更多错误"，而是"给 LLM 提供精准的差异信息"。** L1/L2 只能告诉 LLM"SQL 有问题"，L2.5 能告诉 LLM"分行3的金额少了 30%，多了一个分行13"——LLM 可以据此推断 JOIN 条件或 WHERE 过滤的问题。

### 测试 (3-4 个)

- 完全匹配: 预期数据 = SQL 结果 → `overall_passed=True`
- 数值偏差: 某行金额差 30%，tolerance=1% → 检测到 + 报告偏差
- 缺失行: SQL 结果少了预期中的一行 → `missing_in_actual` 非空
- 多余行: SQL 结果多了一行预期没有的 → `extra_in_actual` 非空

### 面试话术

> "DataPilot 的测试不是只告诉你'有没有错'，而是告诉 LLM '哪里错了、错多少、可能是什么原因'。
>
> 最独特的是预期结果比对——用户把旧系统的正确 CSV 丢进来，我跑完 SQL 后逐行逐列和预期数据做差异分析。分行3的金额少了 30%，多了一个分行13——这些精确的偏差信息会注入 LLM 的诊断上下文。LLM 不再瞎猜'是不是 JOIN 错了'，而是根据'特定分行偏差+特定分行多余'的模式，精准推断出 WHERE 条件或 JOIN 逻辑的具体问题。
>
> 这是银行 ETL 的实战经验——旧系统迁移时，手里一定有上一期的正确结果。把这批数据用起来，比任何语法检查都有价值。"

---

## P6: asyncio 并行化

### 问题

全链路串行。Phase 0 学的 asyncio 零落地。

### 关键并行点

```python
# 1. Supervisor 内: 多个概念同时做语义匹配
await asyncio.gather(*[
    match_async(concept, schema_dict) 
    for concept in concepts
])

# 2. Generator 内: 多策略并行生成 SQL
await asyncio.gather(
    gen_aggregation_sql(...),
    gen_sampling_sql(...),
    gen_distribution_sql(...),
)

# 3. Diagnoser 内: L1 + L2 测试并行
await asyncio.gather(
    run_quality_tests(...),
    run_comparison_tests(...),
)
```

### 实现策略

- `chat_json` 增加 `async` 版本 `chat_json_async`（改 `llm_client.py`）
- 检索增加 `async` 版本
- `cli.py` 保持同步接口，内部用 `asyncio.run()` 驱动

---

## P7: LLM 容错 + Token 追踪补全

### 问题

1. `chat_json` 有 retry，但调用方（concept.py, pseudocode.py）没处理 `RuntimeError`
2. TokenTracker 只在修复闭环 LLM SQL fix 中使用，主 Pipeline 没有

### 修复

```python
# extractor/concept.py
try:
    raw = chat_json(...)
except RuntimeError:
    return ConceptExtractionResult(
        concepts=[],
        raw_requirement=requirement_text,
    )
```

```python
# 主 Pipeline 所有 LLM 调用加 TokenTracker
from callbacks.token_tracker import TokenTracker
tracker = TokenTracker()
raw = chat_json(system_prompt=..., user_message=..., callbacks=[tracker])
```

---

## P8: 端到端集成测试

### 问题

210 tests 全是单元测试。没有端到端流程测试。

### 目标

1 个集成测试文件 `tests/test_e2e.py`：
```python
def test_full_pipeline():
    req = "统计近6个月活跃客户的交易金额"
    sql = run_full_pipeline(req)
    assert "cust_status = '01'" in sql.upper()
    assert "SUM(txn_amt)" in sql.upper()

def test_three_agent_workflow():
    result = run_agent_workflow("统计活跃客户交易金额")
    assert result["status"] == "passed"
```

---

## 当前文件清单（供参考）

```
datapilot/
├── config.py          # LLM/ChromaDB 配置
├── models.py          # 全链路 Pydantic 模型 (187行)
├── llm_client.py      # chat_json + chat_text (172行) → P6 加 async 版本
├── cli.py             # search/analyze 命令 (372行) → P2 加 agent 子命令, P5 加 --expected
├── graph.py           # <<< P2 新增: 3 Agent 编排
├── embedding.py       # BGE 加载
├── extractor/
│   ├── concept.py     # 概念提取 (40行, LLM)
│   ├── prompts.py     # Prompt 集中管理
│   └── assert.py      # <<< P1 新增: 码值→条件翻译
├── retrieval/
│   ├── engine.py      # 分层检索 (134行) → P3 改: 加入两级匹配
│   ├── matcher.py     # 精确+语义匹配
│   ├── ranker.py      # 去重排序
│   ├── schema_reader.py  # <<< P3 新增: information_schema 直读
│   └── vector_match.py   # <<< P3 新增: 向量语义兜底
├── generator/
│   ├── pseudocode.py  # 伪代码生成 (84行, LLM)
│   ├── script.py      # SQL生成 (238行, 规则引擎)
│   └── security.py    # <<< P2 新增: SQL 安全检查
├── testing/
│   ├── quality.py     # L1 基础质量 (488行)
│   ├── comparison.py  # L2 逻辑比对
│   ├── expected_compare.py  # <<< P5 新增: 预期结果比对
│   ├── diagnosis.py   # L3 诊断引擎 (381行)
│   └── llm_tester.py  # LLM 测试生成
├── reconciliation/
│   ├── graph.py       # StateGraph 组装 (123行)
│   ├── nodes.py       # 5个节点 (449行)
│   ├── router.py      # conditional edges
│   └── state.py       # ReconciliationState → P4 加 fix_level
├── callbacks/
│   ├── token_tracker.py
│   └── audit_logger.py
├── dictionary/
│   ├── loader.py      # Excel/CSV → 结构化
│   └── indexer.py     # ChromaDB 向量化 → 保留，标记为语义兜底
├── demo/
│   ├── data_dict.csv
│   ├── req_sample.txt
│   └── generate_dict.py
├── ui/app.py          # Streamlit
└── tests/             # 210 tests → P8 加 test_e2e.py
```

---

## 执行顺序和依赖

```
P1 (1天) ──→ P2阶段A (2天) ──→ P3 (0.5天) ──→ P4 (1天) ──→ P5 (0.5天)
                   ↓
             P6 (1天) ←── P7 (0.5天) ←── P8 (0.5天)

P1 是基础设施: assert.py 是 Supervisor 的核心工具
P2 是架构骨架: graph.py 是 3 Agent 的编排层
P3 是检索升级: information_schema 直读 + 向量兜底，在 Supervisor 内部
P4 是闭环打通: 语义错误回退到 Supervisor，依赖 P2 的编排图
P5 是测试增强: 预期结果比对，依赖 P2 的 Diagnoser Agent
P6/P7/P8: 可独立进行（P6 建议 P3 完成后做，并行检索是性能最大收益点）

总计: ~7 天
```

## 架构决策记录（为什么这样设计）

| 决策 | 理由 |
|------|------|
| 3 Agent 不是 8 Agent | 8 个串行容错太低 (0.95^8=66%)；4 个是工具不是 Agent |
| information_schema 为主，向量兜底 | 精确匹配最快最准；但业务术语≠技术字段名时需语义补充 |
| 断言翻译在 Supervisor 内 | 和 schema 查询强耦合，放一个 Agent 内减少序列化 |
| SQL 安全检查在 Generator 内 | 生成后立刻校验，不通过就修复，短路快 |
| 语义错误回 Supervisor | "表选错了"需要重新理解需求，Supervisor 是唯一有上下文的 |
| asyncio 在 Agent 内部并行 | 3 个 Agent 之间是串行依赖（需要上一步的输出），并行点在内部 |
| 预期结果比对是语义层测试 | L1/L2 只发现"有问题"，L2.5 告诉 LLM "哪里有问题、差多少" |

## 编码前必读

- `agentflow-dev` skill — 35 个共享技术坑（LangChain 1.x / DeepSeek / BGE / Pandas 3.0 等）
- `datapilot-dev` skill — DataPilot 独有踩坑（8个坑，最重要是坑 DP-7: 不能砍功能保稳定）
- TDD 流程: ① 先写测试 → ② 测试失败 → ③ 写最简代码 → ④ 测试通过
