# DataPilot — Project Context for Claude Code

> 最后更新: 2026-05-29 | v3.0

## Project Overview

**DataPilot** — "需求到上线"全链路引擎。从业务需求文档到可执行 SQL、自动测试、修复闭环。

核心能力：业务概念提取(LLM) → 分层检索(DM→DWS→ODS, ChromaDB) → 伪代码生成(LLM) → SQL脚本(规则引擎) → 三层数据测试 → LangGraph修复闭环

## Current Status (2026-05-29)

| Phase | 周期 | 目标 | 状态 |
|-------|------|------|------|
| Phase 1 | Week 1-4 | 需求分析助手 | ✅ 81 tests |
| Phase 2 | Week 5-6 | LangChain重构 + SQL生成 + 基础测试 | 🔄 W5 done, W6 待开始 |
| Phase 3 | Week 7-8 | 逻辑比对 + LangGraph修复闭环 | ⬜ |
| Phase 4 | Week 9-10 | LangSmith + Streamlit + Demo | ⬜ |

**当前: 5/10 周，101 tests**

## Tech Stack

- Python 3.12+
- LLM: DeepSeek `deepseek-chat` (OpenAI 兼容，直连，不用代理)
- Embedding: BGE `bge-small-zh-v1.5` (本地，HF 镜像 `https://hf-mirror.com`)
- 向量库: ChromaDB (持久化 `data/chroma_db/`)
- LangChain 1.x (PromptTemplate + PydanticOutputParser + LCEL + Callbacks)
- LangGraph 1.x (Phase 3: StateGraph + conditional edges + MemorySaver)
- 数据字典: Pandas (Excel/CSV 解析)
- 结构化校验: Pydantic (全链路数据契约)
- WebUI: Streamlit (Phase 4)

## Project Structure

```
D:\datapilot\
├── config.py              # LLM/ChromaDB/BGE 配置
├── models.py              # Pydantic 数据模型
├── llm_client.py          # LLM 调用封装 (chat_json + get_chat_model)
├── cli.py                 # 命令行入口 (search / analyze)
├── README.md
├── requirements.txt
│
├── dictionary/            # 数据字典管理
│   ├── loader.py          #   Excel/CSV → Pydantic DataDictionary
│   └── indexer.py         #   DataDictionary → ChromaDB
│
├── extractor/             # 业务概念提取 (LangChain)
│   ├── prompts.py         #   ChatPromptTemplate 集中管理
│   └── concept.py         #   LCEL: prompt | llm | parser
│
├── retrieval/             # 分层检索引擎
│   ├── engine.py          #   DM→DWS→ODS 层层递进
│   ├── matcher.py         #   精确匹配 + ChromaDB 语义匹配
│   └── ranker.py          #   去重 + 排序
│
├── generator/             # 代码生成
│   ├── pseudocode.py      #   伪代码生成 (LLM)
│   └── script.py          #   SQL 脚本生成 (规则引擎, 非 LLM)
│
├── testing/               # 三层数据测试 (Phase 3)
│   ├── quality.py         #   L1: 基础数据质量
│   ├── comparison.py      #   L2: 逻辑结果比对
│   └── diagnosis.py       #   L3: 诊断引擎 (LLM)
│
├── reconciliation/        # LangGraph 修复闭环 (Phase 3)
│   ├── graph.py           #   StateGraph 定义
│   ├── nodes.py           #   节点函数
│   └── router.py          #   conditional edges
│
├── callbacks/             # LangChain Callbacks
│   ├── token_tracker.py   #   Token 消耗追踪
│   └── audit_logger.py    #   LLM 审计日志
│
├── demo/                  # 演示数据
│   ├── data_dict.csv      #   示例数据字典 (DM/DWS/ODS 三层)
│   └── req_sample.txt     #   示例需求文档
│
└── tests/                 # 101 tests
    ├── test_loader.py
    ├── test_indexer.py
    ├── test_concept.py
    ├── test_retrieval.py
    ├── test_pseudocode.py
    ├── test_script.py
    └── test_integration.py
```

## Key Config (config.py)

```python
# HF 镜像 — 必须在所有 import 之前
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# DeepSeek (OpenAI 兼容)
LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY")
LLM_BASE_URL = "https://api.deepseek.com/v1"
LLM_MODEL = "deepseek-chat"

# ChromaDB
CHROMA_COLLECTION = "data_dictionary"

# BGE Embedding
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
EMBEDDING_DEVICE = "cuda"  # GTX 1060 6GB

# 检索配置
RETRIEVAL_LAYERS = ["DM", "DWS", "ODS"]
RETRIEVAL_TOP_K = 5
RETRIEVAL_THRESHOLD = 0.5
```

## Constraints & Pitfalls

1. **HF_ENDPOINT 必须在 config.py 最顶部** — huggingface_hub 初始化时读取，设晚了无效
2. **DeepSeek 格式不稳定** — 所有 LLM 调用必须有 Pydantic 校验 + retry (最多3次)
3. **config.py 缺少 load_dotenv()** — 需要手动 `set DEEPSEEK_API_KEY` 或加 `.env` 加载
4. **BGE 模型加载两次** — indexer.py 和 matcher.py 各加载一次 (待合并为共享单例)
5. **extractor/concept.py 缺少 retry** — LCEL 链无重试，LLM 格式错误直接抛异常
6. **不做全局代理** — DeepSeek 直连
7. **Windows 中文字体** — 涉及 matplotlib 时用 SimHei
8. **Pandas 3.0+** — `read_sql_query` 已断裂，用 `conn.exec_driver_sql()` 替代

## Coding Standards

- 中文 docstring + type hints
- 新 LLM Prompt 写入 `extractor/prompts.py`，不从代码里拼字符串
- LLM 调用: 简单用 `llm_client.chat_json()`，复杂用 LCEL (`prompt | llm | parser`)
- Pydantic 模型全部定义在 `models.py`
- 测试: 先写测试 → 测试失败 → 最小实现 → 测试通过

## 用户背景（张润泽）

- 6年银行对公数据开发 (ETL/Oracle/Hive/StarRocks)
- 大专学历，全职转型 AI 应用开发
- 不能读英文技术文档 (需翻译)
- 所有解释用 ETL/数据库概念做类比
- DeepSeek 主力 (便宜直连)，OpenAI 仅 Demo
- GPU: GTX 1060 Max-Q 6GB, CUDA 11.8
