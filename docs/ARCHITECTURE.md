# DataPilot 架构文档

> **版本**: v2.0 | **日期**: 2026-05-28 | **状态**: 已确认

---

## 一、项目定位

### 一句话描述

**需求分析加速器——让 Agent 自动完成业务概念到数据模型的层层匹配，解决分析人员不熟悉数仓模型导致的耗时长、易遗漏问题。**

### 核心问题

拿到业务需求文档后，分析人员需要：
1. 理解每个业务概念（"活跃客户"、"渠道"、"近6个月"）
2. 找到对应的数据层和表（DM？DWS？ODS？）
3. 确定字段映射（`cust_status='01'`）
4. 理清码值含义（`01`=活跃、`02`=休眠）
5. 写出分析逻辑伪代码

一个熟悉数仓的分析人员做这些需要 1-2 天，不熟悉的需要 3-5 天，而且容易遗漏、容易出错。

### 解决方案

```
需求文档 ──→ 提取业务概念 ──→ 层层检索数据字典 ──→ 返回匹配结果 ──→ 生成伪代码
                                                  │
                                     DM（集市层）→ 命中 ✓ → 返回
                                          ↓ 未命中
                                     DWS（服务层）→ 命中 ✓ → 返回
                                          ↓ 未命中
                                     ODS（原始层）→ 命中 ✓ → 返回
                                          ↓ 未命中
                                     返回"未找到，请确认"
```

---

## 二、设计原则

1. **翻译是第一优先级**——把模糊业务概念翻译成精确的数据模型定位，比任何技术花活都重要
2. **层层递进**——按数据分层优先级检索（DM → DWS → ODS），匹配到上层的不用查下层。这才是实际需求分析的工作方式
3. **简单替代花哨**——能用精确匹配就不用语义匹配，能返回结构化的就不让 LLM 自由发挥
4. **经验编码进 Prompt**——6 年数据开发的需求分析思路，变成 LLM 的推理框架

---

## 三、系统架构

```
                         ┌─────────────────┐
                         │   Streamlit UI   │  上传需求文档 + 数据字典
                         │   (Phase 2)      │  展示匹配结果 + 伪代码
                         └────────┬────────┘
                                  │
                         ┌────────▼────────┐
                         │   CLI / API      │  命令行入口
                         └────────┬────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
    ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
    │  Concept        │ │  Retrieval      │ │  Pseudo-code    │
    │  Extractor      │ │  Engine         │ │  Generator      │
    │                 │ │                 │ │                 │
    │ 需求文档 →       │ │ 语义匹配 +      │ │ 匹配结果 →       │
    │ 业务概念列表     │ │ 分层递进检索     │ │ 分析逻辑伪代码   │
    └────────┬────────┘ └────────┬────────┘ └────────┬────────┘
             │                   │                   │
             │          ┌────────▼────────┐          │
             │          │  ChromaDB       │          │
             │          │  (数据字典向量库) │          │
             │          └─────────────────┘          │
             │                                       │
             └───────────────────┬───────────────────┘
                                 ▼
                      ┌─────────────────────┐
                      │   匹配结果 + 伪代码   │
                      │   (Markdown/JSON)   │
                      └─────────────────────┘
```

---

## 四、核心模块

### 4.1 数据字典管理

**输入**：人工标注的数据字典（Excel/CSV/JSON），包含以下字段：

| 字段 | 说明 | 示例 |
|------|------|------|
| `layer` | 数据分层 | DM / DWS / ODS |
| `table_name` | 表名 | dm_customer_active |
| `table_comment` | 表注释 | 活跃客户汇总表 |
| `column_name` | 字段名 | cust_status |
| `column_type` | 字段类型 | varchar(2) |
| `column_comment` | 字段注释 | 客户状态 |
| `code_values` | 码值映射 | 01=活跃, 02=休眠, 03=销户 |
| `relations` | 表关系 | cust_id → dim_customer.cust_id |

**存储**：ChromaDB。每个字段+注释+码值作为一条 document，embedding 用本地 BGE 模型。

**分层标记**：`layer` 字段在存入 ChromaDB 时作为 metadata，检索时可以按 layer 过滤。

### 4.2 Concept Extractor（业务概念提取）

**定位**：从需求文档中提取出可检索的业务概念。调一次 LLM。

**输入**：需求文档全文

**输出**：业务概念列表（JSON）

```json
[
  {
    "concept": "活跃客户",
    "context": "各渠道活跃客户数统计",
    "type": "entity",
    "candidates": ["活跃用户", "有效客户", "活跃账户"]
  },
  {
    "concept": "渠道",
    "context": "按渠道维度分组",
    "type": "dimension",
    "candidates": ["渠道来源", "渠道类型"]
  },
  {
    "concept": "近6个月",
    "context": "近6个月有交易记录",
    "type": "time_range",
    "qualifier": "trans_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)"
  }
]
```

**关键细节**：
- `candidates`：让 LLM 生成同义/近义概念，提高检索命中率
- `type`：区分实体、维度、时间范围、度量，后续生成伪代码时有用
- 调一次 LLM，不拆成多次调用

### 4.3 Retrieval Engine（分层检索引擎）

**定位**：核心引擎。按 DM → DWS → ODS 层层检索，每层做语义匹配。

**流程**：

```
业务概念列表
    │
    ▼
┌─────────────────────────────────────┐
│ Layer 1: DM 层检索                   │
│ · 过滤: WHERE layer='DM'            │
│ · 对每个概念 → ChromaDB 语义匹配      │
│ · 收集命中结果（相似度 > 阈值）        │
└──────────────┬──────────────────────┘
               │
         ┌─────▼─────┐
         │ 全部命中？  │
         └─────┬─────┘
         是 ↓        ↓ 否
         返回     ┌─────────────────────────────────────┐
                  │ Layer 2: DWS 层检索                  │
                  │ · 过滤: WHERE layer='DWS'           │
                  │ · 只检索未命中的概念                   │
                  └──────────────┬──────────────────────┘
                                 │
                           ┌─────▼─────┐
                           │ 全部命中？  │
                           └─────┬─────┘
                           是 ↓        ↓ 否
                           返回     ┌─────────────────────────────────────┐
                                    │ Layer 3: ODS 层检索                  │
                                    │ · 过滤: WHERE layer='ODS'           │
                                    │ · 只检索仍未命中的概念                │
                                    └──────────────┬──────────────────────┘
                                                   │
                                             ┌─────▼─────┐
                                             │ 全部命中？  │
                                             └─────┬─────┘
                                             是 ↓        ↓ 否
                                             返回   未命中概念
                                                     → "请确认"
```

**检索策略**：
1. 先精确匹配（表名/字段名直接包含关键词）
2. 再语义匹配（ChromaDB 向量检索）
3. 合并结果，去重排序

**输出**：每个业务概念的匹配结果

```json
{
  "活跃客户": {
    "layer": "DM",
    "table": "dm_customer_active",
    "table_comment": "活跃客户汇总表",
    "columns": [
      {"name": "cust_id", "comment": "客户编号"},
      {"name": "cust_status", "comment": "客户状态", "code_values": {"01": "活跃", "02": "休眠", "03": "销户"}},
      {"name": "last_trans_date", "comment": "最近交易日期"}
    ],
    "score": 0.92
  },
  "渠道": {
    "layer": "DM",
    "table": "dm_channel_summary",
    "columns": [
      {"name": "channel_type", "comment": "渠道类型", "code_values": {"01": "APP", "02": "微信", "03": "柜面"}}
    ],
    "score": 0.88
  }
}
```

### 4.4 Pseudo-code Generator（伪代码生成）

**定位**：基于匹配结果和需求文档，生成分析逻辑伪代码。

**输入**：需求文档 + 匹配结果（表、字段、码值、层信息）

**输出**：结构化伪代码

```text
-- 需求: 统计各渠道活跃客户数
-- 匹配数据层: DM (数据集市层)
-- 主要表: dm_channel_summary, dm_customer_active

步骤 1: 获取活跃客户
  源表: dm_customer_active
  条件: cust_status = '01' (活跃)
       AND last_trans_date >= '2025-11-28' (近6个月)

步骤 2: 关联渠道信息
  左表: dm_channel_summary
  右表: dm_customer_active (步骤1结果)
  关联键: cust_id

步骤 3: 按渠道聚合
  GROUP BY: channel_type
  输出: 渠道类型, 活跃客户数 (COUNT DISTINCT cust_id)
```

**关键约束**：
- 不使用自创的表名、字段名——必须来自匹配结果
- 码值直接写入伪代码（`cust_status = '01'`），不保留业务术语
- 未匹配到的概念用 `-- TODO: 待确认` 标记

---

## 五、技术栈

| 组件 | 选型 | 原因 |
|------|------|------|
| LLM | DeepSeek `deepseek-chat` | 便宜、直连、OpenAI 兼容 |
| Embedding | BGE `bge-small-zh-v1.5`（本地） | 免费、离线、中文优化 |
| 向量库 | ChromaDB | 轻量、持久化、AgentFlow 已验证 |
| 数据字典解析 | Pandas | Excel/CSV 读取 + 结构化 |
| 结构化校验 | Pydantic | Agent 输出校验 |
| WebUI | Streamlit | 快速出界面，上传文件 + 展示结果 |
| 部署 | 纯 Python（不依赖 LangChain/LangGraph） | 逻辑简单，不需要编排框架 |

**为什么不用 LangGraph**：Phase 1 的数据流是线性的——提取概念 → 检索 → 生成伪代码。用 if/else 和函数调用比建 StateGraph 更直观，调试更方便。

---

## 六、目录结构

```
datapilot/
├── README.md
├── requirements.txt
├── .env.example
├── config.py              # LLM/ChromaDB 配置
├── models.py              # Pydantic 数据模型
├── app.py                 # Streamlit WebUI
├── cli.py                 # 命令行入口
│
├── dictionary/            # 数据字典管理
│   ├── loader.py          # Excel/CSV → 结构化 JSON
│   ├── indexer.py         # 结构化 JSON → ChromaDB
│   └── schema.py          # 数据字典 Pydantic 模型
│
├── extractor/             # 业务概念提取
│   └── concept.py         # 需求文档 → 业务概念列表（LLM）
│
├── retrieval/             # 分层检索
│   ├── engine.py          # 检索引擎（DM→DWS→ODS）
│   ├── matcher.py         # 单层匹配（精确+语义）
│   └── ranker.py          # 结果排序 + 去重
│
├── generator/             # 伪代码生成
│   └── pseudocode.py     # 匹配结果 → 伪代码（LLM）
│
├── demo/                  # 演示数据
│   ├── data_dict.xlsx     # 示例数据字典
│   └── req_sample.txt     # 示例需求文档
│
└── tests/
    ├── test_loader.py
    ├── test_concept.py
    ├── test_retrieval.py
    └── test_pseudocode.py
```

---

## 七、约束清单

- DeepSeek `deepseek-chat` 主力
- Embedding 本地 BGE `bge-small-zh-v1.5`，HF 镜像 `https://hf-mirror.com`
- 不做全局代理配置（DeepSeek 直连）
- Pandas 3.0+, ChromaDB 最新稳定版
- Windows 中文字体 `SimHei`（涉及 matplotlib 图表时使用）
- 所有 LLM 调用必须有 Pydantic 输出校验 + retry（最多 3 次）
- 英文技术文档报错需翻译为中文
