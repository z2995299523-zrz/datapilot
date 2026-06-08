# LLM 伪代码→SQL 生成 — 简化设计

> 将 `PseudoCode → SQL` 从规则引擎为主改为 **LLM 直接输出 SQL + 规则引擎 fallback**。
> 不引入新模型、不做结构化中间层。LLM 直接输出 SQL 文本，轻量校验。

## 1. 核心思路

LLM 本来就擅长 SQL 语法。之前出问题是因为 prompt 没给精确上下文——表名带 `(DWS层)` 后缀、中文步骤引用、残缺 JOIN，都是因为 LLM 不知道正确的表名和 CTE 命名规范。

**三个关键动作：**
1. 给精确的元数据（表名、列名、码值）——不靠 LLM 猜
2. 给确定的命名规范（`step_01`, `step_02`）——不产生中文引用
3. 给 few-shot 示例 —— 用模式学习，不靠指令

## 2. 数据流

```
PseudoCode + RetrievalResult
    │
    ▼
_format_step_context()           ← 按步骤裁剪表/字段，只给 LLM 需要的信息
    │
    ▼
build_sql_generation_prompt()    ← 系统 prompt（命名规范 + 1 组 few-shot）+ 用户 prompt（元数据 + 断言）
    │
    ▼
chat_text() → SQL 文本
    │
    ├── 非空 且 含 WITH/SELECT → _build_script_header() + SQL → 完整脚本
    │
    └── 失败/空/格式不对 → generate_sql_script() [规则引擎 fallback]
```

## 3. Prompt 设计（`extractor/prompts.py`）

### 3.1 系统 Prompt

```text
你是 SQL 专家。根据提供的表结构元数据和分析步骤，生成完整的 CTE 链式 SQL 脚本。

## 输出规范

每个分析步骤生成一个 CTE：

WITH
step_01 AS (
    SELECT ...
    FROM 源表
    WHERE ...
),
step_02 AS (
    SELECT ...
    FROM step_01
    LEFT JOIN 关联表 ON 关联条件
    WHERE ...
    GROUP BY ...
)
SELECT ...
FROM step_NN;

## 铁律

1. CTE 名永远用 step_01, step_02, ... 按步骤编号递增
2. 表名/列名只用"可用数据"中列出的，不虚构
3. 断言条件是已知的 WHERE 条件，必须原样使用
4. JOIN 写完整：`LEFT JOIN table_name ON source.col = target.col`
5. 聚合查询必须有 GROUP BY，包含所有非聚合列
6. 未匹配的概念不要凭空写列名，在注释中标注 -- TODO:
```

### 3.2 Few-shot 示例（1 组，两表关联 + 聚合）

```
## 示例输入

需求: 统计各渠道活跃客户数

步骤 1: 筛选活跃客户
  源表: dm_customer_active
  可用列:
    cust_id        — 客户ID (主键)
    cust_status    — 客户状态 (码值: 01=活跃, 02=休眠, 03=销户)
    channel_id     — 渠道ID
    last_trans_date— 最后交易日期
  条件: cust_status = '01' (活跃)
        last_trans_date >= '2025-12-01' (近6个月)
  断言:
    cust_status = '01' → 活跃客户筛选

步骤 2: 按渠道统计客户数
  源表: step_01
  关联表 (JOIN):
    dim_channel — 可用列: channel_id(主键), channel_name(渠道名称), channel_type(渠道类型)
    关联条件: step_01.channel_id = dim_channel.channel_id
  输出: 渠道名称, 活跃客户数

## 示例输出

WITH
step_01 AS (
    SELECT
        cust_id,
        channel_id
    FROM dm_customer_active
    WHERE cust_status = '01'
        AND last_trans_date >= '2025-12-01'
),
step_02 AS (
    SELECT
        dim_channel.channel_name,
        COUNT(DISTINCT step_01.cust_id) AS active_customer_cnt
    FROM step_01
    LEFT JOIN dim_channel
        ON step_01.channel_id = dim_channel.channel_id
    GROUP BY dim_channel.channel_name
)
SELECT
    channel_name,
    active_customer_cnt
FROM step_02
ORDER BY active_customer_cnt DESC;
```

### 3.3 用户 Prompt 模板

```text
## 需求
{requirement_summary}

## 分析步骤
{step_contexts}

## 断言条件（必须原样使用）
{assertions}

## 未匹配概念（不要凭空写列名，标注 -- TODO:）
{unmatched}

请生成完整 SQL 脚本。直接输出 SQL，不要 markdown 代码块。
```

### 3.4 步骤上下文格式化（`_format_step_contexts()`）

不是 dump 全部 retrieval，而是按步骤裁剪。每步给：

```
步骤 1: {description}
  源表: {source_table}
  可用列:
    col_name — comment (码值: v1=m1, v2=m2)
    ...
  条件: {conditions}
  断言: {assertions_matching_this_step}

步骤 2: {description}
  源表: step_01  ← 固定命名
  关联表:
    table_name — 可用列: col1(comment), col2(comment)
    关联条件: {from joins}
  输出: {output}
```

## 4. 入口函数（`generator/script.py`）

新增一个函数，~30 行：

```python
def generate_sql_llm(
    pseudocode: PseudoCode,
    retrieval: RetrievalResult,
    assertions: list[Assertion] | None = None,
    requirement_summary: str = "",
) -> str:
    """LLM 主路径：伪代码 → chat_text → SQL 文本。

    Returns:
        完整 SQL 脚本。失败/空/格式异常时返回 "" → 触发 fallback。
    """
    if not pseudocode.steps:
        return ""

    # 裁剪上下文 + 构建 prompt
    context = _format_step_contexts(pseudocode, retrieval, assertions or [])
    prompt = build_sql_generation_prompt()
    messages = prompt.format_messages(
        requirement_summary=requirement_summary,
        step_contexts=context,
        assertions=_fmt_assertions(assertions or []),
        unmatched=_fmt_unmatched(retrieval.unmatched_concepts),
    )

    tracker = TokenTracker()
    try:
        sql_body = chat_text(
            system_prompt=str(messages[0].content),
            user_message=str(messages[1].content),
            callbacks=[tracker],
        )
    except RuntimeError:
        return ""

    # 轻量校验
    if not sql_body or "SELECT" not in sql_body.upper():
        return ""

    # 代码生成文件头，LLM 生成 SQL 体
    header = _build_script_header(
        pseudocode, retrieval.unmatched_concepts, requirement_summary
    )
    return header + "\n" + sql_body.strip()
```

## 5. 集成改动

### `cli.py:cmd_analyze()`

```python
# 现:
sql = generate_sql(pseudocode, tables, assertions)

# 改为:
sql = generate_sql_llm(pseudocode, result, assertions, req_text[:100])
if not sql:
    print("  LLM SQL 生成失败，使用规则引擎 fallback")
    sql = generate_sql(pseudocode, tables, assertions)
```

### `ui/app.py`

同模式：先调 `generate_sql_llm()`，空则调 `generate_sql_script()`（注意 UI 当前用的是 `generate_sql_script()` 而非 `generate_sql()`）。

### `generator/script.py`

- **新增**：`generate_sql_llm()`, `_format_step_contexts()`
- **不动**：全部现有函数（`generate_sql()`, `generate_sql_script()`, `_build_cte_chain()`, `_build_script_header()`, `_clean_join_clause()`, 等）

## 6. 轻量校验（替代 Pydantic 模型）

| 检查 | 逻辑 |
|------|------|
| 空步骤 | 不调 LLM，直接返回 `""` |
| `chat_text()` 异常 | 返回 `""` |
| 返回空字符串 | 返回 `""` |
| 返回不含 `SELECT` | 返回 `""` — 不尝试修复 |
| 额外：返回不含 `WITH` | 不拒绝（单步骤场景可能没有 CTE），但记录到日志 |

不引入新 Pydantic 模型。校验逻辑 5 行。

## 7. 边界情况

| 情况 | 行为 |
|------|------|
| 无步骤 | → fallback（规则引擎出 `-- 无分析步骤`） |
| retrieval 全部未匹配 | context 中只有步骤描述和条件，LLM 写出 `-- TODO:` 注释 |
| 某步骤无 source_table | context 标注 `源表: (待确认)` |
| 断言为空 | 正常，不影响 |
| LLM 返回 markdown 代码块包裹的 SQL | `chat_text` 结果经 `strip()` 后仍以 `WITH`/`SELECT` 开头就可通过校验；如果被 ```sql 包裹，校验可能漏过但 SQL 仍可读 — 不做 strip 处理，保持简单 |

## 8. 测试策略

**新文件 `tests/test_sql_llm.py`：**

| 测试 | mock | 验证 |
|------|------|------|
| `test_success_single_step` | `chat_text` 返回含 `WITH step_01` 的 SQL | 返回值以 `-- ====` 注释头开头 + 包含 SQL |
| `test_success_two_cte` | 返回完整两句 CTE + 最终 SELECT | 返回值包含 `step_01`, `step_02`, 最终 `SELECT` |
| `test_llm_exception_fallback` | `chat_text` 抛 `RuntimeError` | 返回 `""` |
| `test_empty_response_fallback` | `chat_text` 返回 `""` | 返回 `""` |
| `test_no_select_fallback` | `chat_text` 返回 `"只有注释没有SQL"` | 返回 `""` |
| `test_empty_steps` | 不 mock | 返回 `""`（不调 LLM） |
| `test_header_includes_unmatched` | mock 正常 SQL，unmatched 有值 | 返回值的注释头包含未匹配概念 |
| `test_fallback_to_rule_engine_integration` | `generate_sql_llm` → `""` | 调用 `generate_sql_script()` 并返回非空 |

## 9. 文件变更总览

| 操作 | 文件 | 改动 |
|------|------|------|
| 修改 | `extractor/prompts.py` | 新增系统 prompt + few-shot + 用户模板 + `build_sql_generation_prompt()` |
| 修改 | `generator/script.py` | 新增 `generate_sql_llm()` (~30行) + `_format_step_contexts()` (~50行)；现有函数零改动 |
| 修改 | `cli.py` | `cmd_analyze()` tl>llm 优先 + fallback |
| 修改 | `ui/app.py` | 同上 |
| 新建 | `tests/test_sql_llm.py` | 8 个测试 |
| **不改** | `models.py` | 不引入新模型 |

## 10. 与现有规则引擎的关系

```
                  ┌─ generate_sql_llm()  [新，LLM 主路径]
                  │
generate_sql()  ──┤                          ← cli.py 入口
                  │
                  └─ generate_sql_script()   [现，规则引擎 fallback + UI 当前使用]
                       └─ _build_cte_chain()
                       └─ _build_script_header()
```

`generate_sql()` 逐步淘汰，后续考虑让 `generate_sql_script()` 成为唯一 fallback（它输出 CTE 链，比 `generate_sql()` 的扁平 SELECT 更适合业务场景）。
