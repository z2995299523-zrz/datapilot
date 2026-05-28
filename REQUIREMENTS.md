# DataPilot 项目需求说明文档

> **版本**: v1.0（历史版本）
> **日期**: 2026-05-26
> **作者**: 张润泽 + Hermes Agent
> **状态**: 已过期 — 当前实现见 `docs/ARCHITECTURE_V3.md`
>
> ⚠️ 本文档描述的是 8 Agent + 三层测试的 v1.0 规划架构，与当前 v2.0/v3.0 的实现
> 有较大差异。保留本文档作为架构演进的历史参考。

---

## 一、项目定位

### 一句话描述

**AI 驱动的数据核对平台——让 Agent 自动完成原来需要 3 个人、2 周的数据核对工作。**

### 核心问题

企业数据系统迁移/改造时，数据核对是最痛苦、最重复、最容易出错的工作。现有工具（商业软件 Monte Carlo/Datafold）收费且闭源，开源社区没有任何成熟的 AI 数据核对 Agent 方案。

### 目标用户

- 数据开发/测试团队（任何需要做数据核对的场景）
- 系统迁移、数仓重构、报表上线前的数据验证

### 与 AgentFlow 的关系

| | AgentFlow | DataPilot |
|---|---|---|
| 定位 | 通用 AI 助手（RAG+SQL+对话） | 专业数据核对平台 |
| 证明什么 | "我会这些技术栈" | "我能解决实际问题" |
| 简历比重 | 30% | 70% |
| 代码复用 | — | 复用 LangGraph 模式、DeepSeek 配置 |

**两个项目独立仓库，不互相依赖。**

---

## 二、架构总览

### 2.1 Agent 角色定义（8 个）

```
用户输入：需求文档 + 加工脚本 + 数据库连接
                    │
                    ▼
    ┌───────────────────────────────┐
    │         Supervisor Agent      │  意图识别 + 任务分解 + 调度
    └───────────────┬───────────────┘
                    │
       ┌────────────┼────────────┬──────────┐
       ▼            ▼            ▼          ▼
┌───────────┐ ┌───────────┐ ┌───────────┐ ┌──────────────┐
│Knowledge  │ │ Parse     │ │ Assert    │ │ Gen Agent    │
│Retrieval  │ │ Agent     │ │ Agent     │ │ (测试生成)    │
│(数据模型   │ │ (脚本解析) │ │ (需求→断言)│ │              │
│ RAG检索)  │ │           │ │           │ │              │
└─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └──────┬───────┘
      │             │             │              │
      └──────┬──────┴──────┬──────┴──────┬───────┘
             │             │             │
             ▼             ▼             ▼
      ┌───────────┐ ┌───────────┐ ┌───────────┐
      │ Exec      │ │ Analyze   │ │ Report    │
      │ Agent     │ │ Agent     │ │ Agent     │
      │ (执行引擎) │ │ (差异分析) │ │ (报告生成) │
      └───────────┘ └───────────┘ └───────────┘
```

| # | Agent | 职责 | 输入 | 输出 |
|---|-------|------|------|------|
| 1 | **Supervisor** | 理解用户意图，拆解核对任务，调度子Agent | 用户自然语言 | 子任务列表 + 路由决策 |
| 2 | **Knowledge Retrieval** | 检索企业数据模型（表结构/字段/码值/表关系），为 Assert Agent 提供上下文 | 业务概念关键词 | 匹配的表、字段、码值映射 |
| 3 | **Parse Agent** | 三阶段解析复杂SQL脚本，输出步骤DAG | SQL脚本文本 | 版本化的步骤依赖图 |
| 4 | **Assert Agent** | 从需求文档推导可验证的数据断言 | 需求文档 + 数据模型上下文 | 结构化断言（JSON） |
| 5 | **Gen Agent** | 根据三个层的测试需求生成验证SQL | 步骤描述 + 断言 + 表结构 | 验证SQL列表（6种策略） |
| 6 | **Exec Agent** | 安全执行SQL，收集结果 | SQL列表 + DB连接 | 执行结果（DataFrame） |
| 7 | **Analyze Agent** | 差异智能分类 + 根因定位 | 执行结果 + 断言 | 结构化差异报告 |
| 8 | **Report Agent** | 生成最终核对报告 | 所有中间结果 | Markdown报告 |

### 2.2 三层测试体系

这是 DataPilot 的核心竞争力——不只是"两张表 count 一下"。

```
┌──────────────────────────────────────────────┐
│ Layer 1: 需求 → 数据断言                       │
│ 从模糊的业务需求推导出精确的数据条件              │
│ 例："活跃客户" → cust_status='01' AND 近6月有交易 │
│ 这一层回答：数据做对了业务要的事吗？              │
├──────────────────────────────────────────────┤
│ Layer 2: 脚本 → 步骤验证                       │
│ 解析复杂脚本的每个中间步骤，逐层生成验证          │
│ 例：第3个临时表的LEFT JOIN是否丢失了数据？        │
│ 这一层回答：脚本逻辑正确执行了吗？                │
├──────────────────────────────────────────────┤
│ Layer 3: 新旧系统 → 结果核对                   │
│ 传统的数据对比，但自动选择6种策略 + 差异分类      │
│ 这一层回答：新系统数据和老系统一致吗？             │
└──────────────────────────────────────────────┘
```

---

## 三、核心模块详细设计

### 3.1 Knowledge Retrieval（数据模型 RAG）

**问题**：需求文档说"活跃客户"，Agent 如果不认识企业的数据模型，根本不知道"活跃"对应哪个字段、哪个码值。

**方案**：在 Assert Agent 之前插入 Knowledge Retrieval 节点。

**流程**：
```
需求文档 → 提取业务概念 → 检索数据模型 → 注入映射关系 → Assert Agent 生成断言

示例：
"活跃客户" → 检索 → dim_customer.cust_status 字段
                    → 码值 '01'=活跃, '02'=休眠, '03'=销户
                    → transactions 表近6个月有记录
         → 注入 → Assert Agent: "活跃客户 = cust_status='01' AND 近6月有交易"
```

**数据模型来源**（按优先级）：
1. 数据库自动提取（JDBC 连接 → 读取 information_schema → 表名+字段+注释+码值表）
2. 用户手动上传（数据字典 Excel、DDL 文件）
3. RAG 检索（向量化存储，语义匹配业务概念到表和字段）

**技术实现**：
- 用 ChromaDB 存储数据模型（表名/字段名/注释/码值 → embedding）
- 检索策略：先精确匹配表名/字段名，再语义匹配业务概念
- 码值映射特殊处理：`cust_status` 字段自动关联 `dim_code` 表获取码值含义

---

### 3.2 Parse Agent（三阶段脚本解析）

**问题**：
1. 复杂脚本包含多个临时表，同名临时表可能被覆盖重赋值
2. 500+ 行脚本 LLM 一次处理会精度下降

**方案**：三阶段解析

```
原始 SQL 脚本（可能 500+ 行）
        │
        ▼
┌──────────────────────┐
│ 阶段 1: 结构切片      │  纯规则，不调 LLM
│ - 按 DROP/CREATE 切分 │  识别临时表的"生命周期"
│ - 版本化命名          │  每次 CREATE 开始新实例：tmp#v1, tmp#v2...
│ - 输出 N 个代码块     │  每块 50-150 行
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ 阶段 2: 逐块 LLM 解析 │  并行处理，每块独立调 LLM
│ - 块内语义理解        │  上下文短（<150行），精度高
│ - 依赖识别           │  记录本块引用了哪些上游表
│ - 边界条件探测        │  LEFT JOIN? GROUP BY? 窗口函数?
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ 阶段 3: 依赖组装      │  纯逻辑，不调 LLM
│ - 按版本号组装 DAG    │  同一表名不同版本 = 不同节点
│ - 检测覆盖/重赋值     │  tmp#v1 → tmp#v2 标记覆盖关系
│ - 检测悬空引用        │  引用了不存在的表版本
└──────────────────────┘
```

**版本化命名的关键逻辑**：

```sql
-- 阶段1扫描这段SQL后的输出：
-- tmp_result#v1:  L1-L5    (第一次定义)
-- tmp_summary#v1: L7-L10   (依赖 tmp_result#v1)
-- tmp_result#v2:  L13-L16  (第二次定义，覆盖 v1，依赖 tmp_summary#v1)

-- 依赖图:
-- tmp_result#v1 → tmp_summary#v1 → tmp_result#v2 → 最终输出

-- 如果某处引用了 tmp_result，需要判断：
-- - 在 L7-L10 之间引用 → 指向 v1
-- - 在 L13 之后引用 → 指向 v2
```

**窗口函数的处理**：
- sqlparse 对 `ROW_NUMBER() OVER (PARTITION BY ...)` 支持有限
- 阶段1不做完整解析，只识别 CREATE/DROP/INSERT 边界
- 窗口函数的具体语义在阶段2由 LLM 理解
- 降级方案：sqlparse 解析失败 → 整块交给 LLM

---

### 3.3 Assert Agent（需求→断言）

**输入**：需求文档 + Knowledge Retrieval 提供的表/字段/码值映射

**输出**：结构化断言（JSON），覆盖 5 种断言类型

| 断言类型 | 说明 | 示例 |
|---------|------|------|
| completeness | 完整性：数据不应有遗漏 | 近6个月有交易客户不应缺失 |
| exclusion | 排除性：不应包含的数据 | 结果中不应包含已销户客户 |
| coverage | 覆盖性：应包含的数据 | 产品维度表中所有产品类型都应出现 |
| domain | 值域：字段取值范围 | product_type 必须在 dim_product 中有定义 |
| consistency | 一致性：聚合一致性 | 各产品 cnt 之和 ≈ 总数 |

**技术关键**：
- 不是 LLM 拍脑袋生成，而是先检索到具体表和字段，再生成针对性的断言
- 每个断言附带可执行的验证 SQL
- 用 Pydantic 校验输出结构，DeepSeek 不稳定时自动 retry

---

### 3.4 Gen Agent（测试生成）

**输入**：Parse Agent 的步骤 DAG + Assert Agent 的断言列表 + 表结构信息

**输出**：按 6 种策略生成的验证 SQL

| 策略 | 说明 | 适用场景 | 示例 |
|------|------|---------|------|
| 总量核对 | COUNT、SUM(key_field) | 所有步骤 | `SELECT COUNT(*) FROM tmp_active` |
| 抽样核对 | 随机 N 条全字段对比 | 大表（>100万行） | `SELECT * FROM tmp_active ORDER BY RAND() LIMIT 100` |
| 分布核对 | 按维度 GROUP BY 对比 | 有 GROUP BY 的步骤 | `SELECT product_type, COUNT(*) FROM tmp_summary GROUP BY 1` |
| 边界核对 | 临界值检查 | 有 WHERE 条件的步骤 | `SELECT * FROM tmp_active WHERE total_amt = 1000` |
| 关联核对 | JOIN 字段完整性 | LEFT/RIGHT JOIN 步骤 | `SELECT COUNT(*) FROM tmp_active LEFT JOIN dim ON ... WHERE dim.key IS NULL` |
| 空值核对 | NULL 值比例 | 所有步骤 | `SELECT SUM(CASE WHEN cust_name IS NULL THEN 1 ELSE 0 END) / COUNT(*) FROM result` |

**策略选择逻辑**（你的 6 年经验编码成规则）：
- 大表（>100万行）：优先总量 + 抽样，不做全字段逐值
- 有主键：哈希比对优先
- 有 GROUP BY：必须做分布核对
- 有 LEFT JOIN：必须做关联核对（这是最容易出错的）
- 日期分区表：只核对最近 N 天 + 抽查历史

---

### 3.5 Exec Agent（执行引擎）

**功能**：
- 批量执行生成的验证 SQL
- 支持双数据库连接（旧系统 + 新系统）
- 并发执行 + 超时控制（大表查询设上限）
- SQL 安全检查（拦截 DROP/DELETE/TRUNCATE/ALTER）
- 结果缓存（同一 SQL 不重复执行）

**安全检查规则**：
```python
FORBIDDEN_KEYWORDS = ['DROP', 'DELETE', 'TRUNCATE', 'ALTER', 'UPDATE', 'INSERT', 'CREATE']
# 只允许 SELECT 和 EXPLAIN
```

---

### 3.6 Analyze Agent（差异分析）

**不只是"不一致"，而是解释"为什么不一致"：**

| 差异类型 | 判断特征 | 置信度 | 行动建议 |
|---------|---------|--------|---------|
| 🔴 数据遗漏 | 某批次/某天数据完全缺失 | 高 | 检查迁移脚本，最高优先级 |
| 🟡 口径差异 | 差异比例稳定（如全部×1.1） | 高 | 确认业务口径，标记为预期差异 |
| 🟡 JOIN 丢失 | LEFT JOIN 侧数据量减少 | 中 | 检查维表是否完整同步 |
| 🔴 计算错误 | 聚合结果不同但原始数据一致 | 高 | 检查聚合逻辑，高优先级 |
| 🟢 精度差异 | 小数位数不同 | 高 | 低优先级，记录即可 |
| 🟢 排序差异 | 内容相同顺序不同 | 高 | 无影响，忽略 |
| ⚪ 未知 | 不符合以上模式 | 低 | 人工介入 |

**分析流程**：
```
差异数据 → Pandas 特征提取 → LLM 分类推理 → 定位到具体步骤 → 给出建议

特征包括：
- 差异比例（稳定/随机/全有全无）
- 差异字段类型（金额/日期/字符串/枚举）
- 关联表完整性
- 时间分布（只在某段时间出现？）
```

---

### 3.7 Report Agent（报告生成）

**输出**：Markdown 格式核对报告，包含：
1. 核对概要（总表数/通过数/差异数/耗时）
2. 三层测试结果
3. 差异明细（分类标注 + 根因分析 + 建议）
4. 步骤级 DAG 可视化（ASCII/Mermaid）
5. 行动建议（按优先级排序）

---

### 3.8 Supervisor Agent（调度中心）

**意图识别**：
- "核对两张表" → Layer 3 only
- "测试这个脚本对不对" → Layer 2 + 3
- "按需求文档核对数据" → Layer 1 + 2 + 3（全量）
- "只看需求层面的差异" → Layer 1 only

**任务分解**：
- 多表核对按依赖关系排序（基础表→汇总表，和你调度 ETL 一样）
- 独立表并行核对
- 某张表核对失败 → 标记，继续核对下游

---

## 四、技术栈

| 组件 | 选型 | 原因 |
|------|------|------|
| Agent 编排 | LangGraph 1.x | 你在 AgentFlow 中已掌握 |
| LLM | DeepSeek `deepseek-chat` | 便宜、国内可用、OpenAI 兼容 |
| Embedding | BGE `bge-small-zh-v1.5`（本地） | 免费、离线、中文优化 |
| 向量库 | ChromaDB | 轻量、持久化、在 AgentFlow 已验证 |
| 数据库连接 | SQLAlchemy 2.0 | 多数据库方言支持 |
| 数据处理 | Pandas | 差异分析、统计 |
| SQL 解析 | sqlparse | 结构切片 + LLM 语义理解 |
| API | FastAPI（后期可选） | 如果需要对外提供接口 |
| WebUI | Streamlit | 快速出界面，在 AgentFlow 已验证 |
| 结构化校验 | Pydantic | Agent 输出校验 |
| 部署 | Docker | 一键部署 |

---

## 五、项目结构（规划）

```
datapilot/
├── README.md
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── start.bat / start.sh
│
├── config.py              # LLM/DB/Chroma 配置
├── models.py              # Pydantic 数据模型
├── app.py                 # Streamlit WebUI
│
├── knowledge/             # 数据模型 RAG
│   ├── schema_loader.py   # 从数据库自动提取表结构
│   ├── code_loader.py     # 码值映射加载
│   └── retriever.py       # 语义检索业务概念→表/字段
│
├── parse/                 # 脚本解析
│   ├── slicer.py          # 阶段1: 规则切片 + 版本化
│   ├── semantic.py        # 阶段2: LLM 语义理解
│   └── dependency.py      # 阶段3: DAG 组装
│
├── assert_agent/          # 需求→断言
│   └── generator.py       # 断言生成
│
├── gen/                   # 测试生成
│   ├── strategies.py      # 6种测试策略模板
│   ├── step_generator.py  # Layer 2: 步骤验证SQL
│   ├── compare_generator.py # Layer 3: 新旧对比SQL
│   └── assert_generator.py # Layer 1: 断言验证SQL
│
├── exec/                  # 执行引擎
│   ├── runner.py          # SQL 执行 + 并发控制
│   └── sandbox.py         # SQL 安全检查
│
├── analyze/               # 差异分析
│   ├── feature.py         # 差异特征提取（Pandas）
│   ├── classifier.py      # LLM 差异分类
│   └── root_cause.py      # 根因定位
│
├── report/                # 报告生成
│   └── generator.py       # Markdown 报告
│
├── graph/                 # LangGraph 编排
│   ├── state.py           # 状态定义
│   ├── nodes.py           # 8个节点实现
│   └── workflow.py        # 图构建 + 路由
│
├── tests/                 # 测试
│   ├── test_slicer.py
│   ├── test_semantic.py
│   ├── test_dependency.py
│   ├── test_assert.py
│   ├── test_gen.py
│   ├── test_exec.py
│   ├── test_analyze.py
│   └── test_workflow.py
│
└── demo/                  # 演示场景
    ├── scenario_1/        # 简单表核对
    ├── scenario_2/        # 复杂脚本核对（5个临时表嵌套）
    └── scenario_3/        # 需求层面核对
```

---

## 六、3 个演示场景（面试用）

### 场景 1：简单表核对（2 分钟）
> 配置两个数据库 → 选表 → Agent 自动选择核对策略 → 运行 → 输出差异

**面试话术**："这是基础功能。但不是简单的 count + diff——Agent 会自动判断表的主键、选择合适的核对策略。大表用哈希比对，小表全字段逐值对比。"

### 场景 2：复杂脚本核对（5 分钟，核心亮点）
> 上传一个信贷系统的 ETL 脚本（5 个临时表嵌套，含同名覆盖）→ Agent 解析 → 逐层验证 → 第 3 个临时表 LEFT JOIN 丢失数据被定位

**面试话术**："这个脚本有 5 个临时表，第 3 个和最后一个是同名覆盖的。传统测试只能对比最终结果——结果不对你不知道是哪一步的问题。我的 Agent 把脚本切成 5 个独立步骤，为每一步生成验证用例，所以能精准定位到是 LEFT JOIN 的维表没同步完整。"

### 场景 3：需求层面核对（3 分钟，差异化壁垒）
> 上传需求文档 + 数据模型 → Agent 读需求生成断言 → 加载脚本 → 发现脚本用 `status='ACTIVE'` 但需求定义"近 6 月有交易" → 标记需求-逻辑不一致

**面试话术**："数据系统最大的问题不是脚本写错，是需求理解错。因为没有人把模糊的业务概念翻译成精确的数据条件。我的 Agent 做了三层校验——需求层、逻辑层、结果层——每一层对应我在数据开发中见过的不同出错模式。"

---

## 七、开发约束

### 7.1 技术约束（继承自 AgentFlow 的教训）

| 约束 | 说明 |
|------|------|
| LLM 主力 | DeepSeek `deepseek-chat`，OpenAI 只用于 Demo 录制 |
| Embedding | 本地 BGE `bge-small-zh-v1.5`，GPU 加速（GTX 1060 6GB） |
| HF 镜像 | `HF_ENDPOINT=https://hf-mirror.com`，**必须在 config.py 最前面设置** |
| LangChain | 1.x，不用 0.x 语法 |
| LangGraph | 1.1.3+ |
| Pandas | 3.0+，`read_sql_query` 已断裂，用 `conn.exec_driver_sql()` 替代 |
| SQLAlchemy | 2.0 |
| Windows | 中文字体 `SimHei` + `plt.style.use()` 之后设 rcParams |
| 代理 | 项目全局不用代理（DeepSeek 直连） |
| DeepSeek 不稳定 | Tool-calling 模式 + suffix 强制格式 + 解析兜底提取 |

### 7.2 开发流程约束（Superpowers 方法论）

```
每个任务必须：
  1. 先写测试 → 2. 测试必须失败 → 3. 写最简代码 → 4. 测试通过
  5. 规格审查（做对了吗？没多做？）→ 6. 质量审查（写得好吗？）
  7. 全部通过 → 下一个任务
```

### 7.3 用户约束

- 不能阅读英文技术文档 → 报错需翻译
- 有 6 年数据开发经验 → 用数据库/SQL/ETL 概念做类比
- 代码讲解不能简短 → 每个模块必须六步法深度讲解 + 写入笔记

---

## 八、成功标准

- [ ] GitHub 搜索"数据核对 Agent"能看到 DataPilot
- [ ] 3 个演示场景可流畅录制
- [ ] 差异分类准确率 ≥ 85%（20 个标注样本验证）
- [ ] 端到端核对时间 < 5 分钟（中等复杂度脚本）
- [ ] README 有架构图 + 演示 GIF + 面试话术
- [ ] 面试中能围绕这个项目独立讲 15 分钟

---

## 九、待决议题

以下问题需要在实现前确认：

1. **数据库方言**：首期支持 MySQL + StarRocks？还是只做 MySQL？（你最熟什么？）
2. **数据模型来源**：首期手动上传数据字典 Excel，还是直接连接数据库自动读取 schema？
3. **脚本格式**：首期只支持纯 SQL（.sql 文件），还是也支持存储过程？
4. **WebUI 时机**：是先做 CLI 版本快速验证，还是 Week 1 就开始 Streamlit？
