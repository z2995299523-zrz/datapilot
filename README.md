# DataPilot

> **"需求到上线"全链路引擎** — 从业务需求文档到可执行 SQL、自动测试、修复闭环。

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![LangChain](https://img.shields.io/badge/LangChain-1.x-green.svg)](https://www.langchain.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.x-orange.svg)](https://www.langchain.com/langgraph)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-latest-purple.svg)](https://www.trychroma.com/)
[![Tests](https://img.shields.io/badge/tests-101-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

---

## 解决什么问题

企业数据分析团队的真实痛点不是某一步难，而是**每一步之间的断层**：

```
需求分析 → 模型定位 → 脚本开发 → 数据测试 → 逻辑核对 → 修复 → 上线
```

| 环节 | 谁做 | 问题 |
|------|------|------|
| 需求分析 → 模型定位 | 分析人员 | 不熟悉数仓模型，耗 1-3 天，容易遗漏 |
| 模型定位 → 脚本开发 | 开发人员 | 分析结论传递失真，理解偏差 |
| 脚本开发 → 数据测试 | 测试人员 | 测试用例靠人工写，覆盖不全 |
| 测试失败 → 修复 | 全员 | 问题定位靠经验，反复对齐 |

DataPilot 用 **LangChain + LangGraph** 把这条链路自动化：**传一个需求文档，得到一个通过测试的 SQL 脚本**。

---

## 全链路架构

```
需求文档.txt
    │
    ▼
┌─────────────────────────────────────────┐
│ Layer 1: 需求 → SQL（纯 Python + LCEL）   │
│                                         │
│  概念提取(LLM) → 分层检索(DM→DWS→ODS)   │
│  → 伪代码生成(LLM) → SQL脚本(规则引擎)    │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│ Layer 2: 三层数据测试（testing/）         │
│                                         │
│  L1 基础质量: 主键唯一/空值率/超长/码值   │
│  L2 逻辑比对: 原始表聚合 vs 结果表        │
│  L3 诊断引擎: 五级诊断链路(LLM)           │
└──────────────────┬──────────────────────┘
                   │ 失败
                   ▼
┌─────────────────────────────────────────┐
│ Layer 3: LangGraph 修复闭环               │
│                                         │
│  run_tests → pass → END                 │
│           → fail → diagnose             │
│                  → auto → auto_fix → 重测│
│                  → manual → 人工报告     │
└─────────────────────────────────────────┘
```

---

## 技术栈

| 技术 | 用途 | 层级 |
|------|------|------|
| **LangChain** | PromptTemplate + PydanticOutputParser + LCEL + Callbacks | LLM 交互 |
| **LangGraph** | StateGraph + conditional edges + MemorySaver | 修复闭环 |
| **ChromaDB** | 数据字典向量库 + metadata filtering | 分层检索 |
| **BGE** | 本地中文语义匹配（bge-small-zh-v1.5） | Embedding |
| **DeepSeek** | LLM 推理（OpenAI 兼容协议） | 主力模型 |
| **Pydantic** | 全链路数据契约 + State Schema | 结构化校验 |
| **Streamlit** | WebUI（Phase 4） | 演示 |

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
# Windows
set DEEPSEEK_API_KEY=your-key

# Linux/Mac
export DEEPSEEK_API_KEY=your-key
```

### 3. 构建数据字典索引

```bash
python -m dictionary.indexer demo/data_dict.csv
```

### 4. 运行需求分析

```bash
# 仅检索
python cli.py search --req demo/req_sample.txt --verbose

# 完整链路（概念 → 检索 → 伪代码）
python cli.py analyze --req demo/req_sample.txt --verbose
```

---

## 目录结构

```
datapilot/
├── config.py                 # LLM/ChromaDB 配置
├── models.py                 # Pydantic 数据模型 + LangGraph State
├── llm_client.py             # LLM 调用封装
├── cli.py                    # 命令行入口
│
├── dictionary/               # 数据字典管理
│   ├── loader.py             # Excel/CSV → 结构化
│   └── indexer.py            # ChromaDB 向量化
│
├── extractor/                # 业务概念提取（LangChain）
│   ├── prompts.py            # LLM Prompt 集中管理
│   └── concept.py            # LCEL 链式调用
│
├── retrieval/                # 分层检索
│   ├── engine.py             # DM→DWS→ODS 递进
│   ├── matcher.py            # 精确 + 语义匹配
│   └── ranker.py             # 去重排序
│
├── generator/                # 代码生成
│   ├── pseudocode.py         # 伪代码生成（LLM）
│   └── script.py             # SQL 脚本生成（规则引擎）
│
├── testing/                  # 三层测试（Phase 3）
│   ├── quality.py            # L1: 基础数据质量
│   ├── comparison.py         # L2: 逻辑结果比对
│   └── diagnosis.py          # L3: 诊断引擎
│
├── reconciliation/           # LangGraph 修复闭环（Phase 3）
│   ├── graph.py              # StateGraph 定义
│   ├── nodes.py              # 节点函数
│   └── router.py             # conditional edges
│
├── callbacks/                # LangChain Callbacks
│   ├── token_tracker.py      # Token 消耗追踪
│   └── audit_logger.py       # LLM 审计日志
│
├── demo/                     # 演示数据
│   ├── data_dict.csv         # 示例数据字典
│   └── req_sample.txt        # 示例需求文档
│
└── tests/                    # 101 tests
```

---

## 开发进度

| Phase | 周期 | 目标 | 状态 |
|-------|------|------|------|
| Phase 1 | Week 1-4 | 需求分析助手（概念→检索→伪代码） | ✅ 81 tests |
| Phase 2 | Week 5-6 | LangChain 重构 + 脚本生成 + 基础测试 | 🔄 W5 done |
| Phase 3 | Week 7-8 | 逻辑比对 + LangGraph 修复闭环 | ⬜ |
| Phase 4 | Week 9-10 | LangSmith + Streamlit + Demo | ⬜ |

**当前: 5/10 周，101 tests**

---

## 技术决策

| 决策 | 方案 | 理由 |
|------|------|------|
| 线性管道 | 纯 Python/Pydantic | 步骤固定（DM→DWS→ODS 不可绕过），不需 Agent 编排 |
| LLM 交互 | LangChain | PromptTemplate 集中管理 + OutputParser 自动校验 |
| 修复闭环 | LangGraph | 条件路由显式声明 + checkpointer 审计追溯 |
| 脚本生成 | 规则引擎（非 LLM） | 语法确定性，不受 LLM 不稳定影响 |
| JOIN 键推断 | 三级：字典外键 → 同名字段 → _id 后缀 | 优先人工标注，降级自动推断 |

---

## License

MIT
