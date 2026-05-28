# DataPilot 项目计划

> **版本**: v2.0 | **日期**: 2026-05-28 | **目标**: 4 周内完成需求分析助手 MVP

---

## 一、总体分 Phase

| Phase | 周期 | 目标 | 交付物 |
|-------|------|------|--------|
| Phase 1 | Week 1-2 | 数据字典入库 + 检索 | CLI 上传字典 → 检索业务概念 |
| Phase 2 | Week 3-4 | 需求分析全链路 + 伪代码 | 上传需求文档 → 完整匹配报告 |
| Phase 3 | Week 5 | 界面 + 打磨 | Streamlit + Demo 录制 |

---

## 二、Phase 1: 数据字典 + 检索引擎（Week 1-2）

### Week 1: 项目骨架 + 数据字典

| 任务 | 模块 | 输出 |
|------|------|------|
| 项目初始化 | `config.py`, `models.py`, `.env.example` | 目录结构、依赖锁定 |
| 数据字典解析 | `dictionary/loader.py` | Excel/CSV → 结构化 JSON（Pandas） |
| 数据模型定义 | `dictionary/schema.py` | Pydantic: `TableDict`, `ColumnDict` |
| ChromaDB 索引 | `dictionary/indexer.py` | 结构化 JSON → ChromaDB（BGE embedding） |
| 演示数据 | `demo/data_dict.xlsx` | 一个包含 DM/DWS/ODS 三层的示例字典 |
| 测试 | `tests/test_loader.py` | loader 单元测试 |

**里程碑**: `python -m dictionary.indexer --input demo/data_dict.xlsx` 成功建库。

**技术要点**：
- ChromaDB 持久化到 `data/chroma_db/`
- 每条 document 的 metadata 包含 `layer`, `table_name`, `column_name`
- Embedding 文本 = `table_comment + column_name + column_comment + code_values`
- `config.py` 第一行：`os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'`

### Week 2: 概念提取 + 分层检索

| 任务 | 模块 | 输出 |
|------|------|------|
| 概念提取 Prompt | `extractor/concept.py` | 需求文档 → LLM → 业务概念 JSON |
| 分层检索引擎 | `retrieval/engine.py` | DM→DWS→ODS 层层递进检索 |
| 单层匹配 | `retrieval/matcher.py` | 精确匹配 + ChromaDB 语义匹配 |
| 结果排序 | `retrieval/ranker.py` | 去重 + 按相似度排序 |
| 测试 | `tests/test_concept.py`, `tests/test_retrieval.py` | 概念提取 + 检索测试 |
| Demo 数据 | `demo/req_sample.txt` | 示例需求文档 |

**里程碑**: `python cli.py search --req demo/req_sample.txt` 返回匹配结果。

**检索策略细节**：
1. 对每个概念 + candidates，先用精确匹配（表名/字段名包含关键词）快速过滤
2. 精确没命中 → ChromaDB 语义检索（带 `layer` filter）
3. 同一概念命中多个结果 → 取相似度最高的
4. 记录每层检索日志（命中/未命中/降级），用于面试时展示

---

## 三、Phase 2: 需求分析全链路（Week 3-4）

### Week 3: 伪代码生成 + 链式调用

| 任务 | 模块 | 输出 |
|------|------|------|
| 伪代码 Prompt | `generator/pseudocode.py` | 需求文档 + 匹配结果 → LLM → 伪代码 |
| 链式调用 | `cli.py` | Concept → Retrieval → PseudoCode 一条命令 |
| 未命中处理 | `retrieval/` | 返回 "未找到，请确认" 结构 |
| 日志输出 | `retrieval/` | 每层检索详情（命中哪些、降级哪些） |

**里程碑**: `python cli.py analyze --req demo/req_sample.txt` 输出完整报告。

**伪代码生成约束**：
- 不使用虚构的表名/字段名
- 码值直接写出（`'01'` 而非 "活跃"）
- 未匹配概念标注 `-- TODO: 待确认数据源`
- 包含数据层来源标注（`-- 来自 DM 层`）

### Week 4: 联调 + 边界情况

| 任务 | 输出 |
|------|------|
| 全链路联调 | 需求文档 → 分析报告 端到端 |
| 边界场景 | 全部未命中 / 部分命中 / DM+DWS 跨层命中 |
| 多概念关联 | "活跃客户的交易金额" — 两个概念关联到不同表 |
| 检索日志优化 | 展示每层的检索过程（可追溯） |
| CLI 完善 | 命令行参数 + 输出格式化（Markdown/JSON） |

**里程碑**: 3 种边界场景 + 1 个正常场景全部通过。

---

## 四、Phase 3: 界面 + 打磨（Week 5）

| 任务 | 输出 |
|------|------|
| Streamlit 页面 | 上传字典 → 建索引 → 上传需求 → 查看报告 |
| Demo 场景 | 一个真实信贷需求文档 + 完整数据字典 |
| 录制 | 操作流程 GIF/视频 |
| README | 架构图 + Demo 展示 + 快速开始 + 面试话术 |
| GitHub 发布 | 搜索优化、标签 |

---

## 五、开发约束

### 5.1 每个任务的工作流

```
1. 写测试 → 2. 确认失败 → 3. 最小实现 → 4. 通过
   ↓
5. 规格审查 → 6. 质量审查 → 7. 下一个任务
```

### 5.2 技术约束

- DeepSeek `deepseek-chat` 主力，OpenAI 仅 backup
- BGE `bge-small-zh-v1.5`，HF 镜像 `https://hf-mirror.com`
- ChromaDB 持久化模式
- 纯 Python 模块，不引入 LangChain/LangGraph（线性流程不需要编排框架）
- LLM 输出必须有 Pydantic 校验 + retry

### 5.3 用户约束

- 英文报错需翻译
- 类比用数据库/SQL/ETL 概念
- 每个模块六步法深度讲解 + 笔记

---

## 六、风险

| 风险 | 应对 |
|------|------|
| BGE embedding 中文语义匹配不准 | 增加 candidates 同义词扩展 + 精确匹配兜底 |
| DeepSeek 返回格式不稳定 | Pydantic 校验 + retry + 解析降级提取 |
| 数据字典格式不统一 | `loader.py` 做格式推断 + 用户手动映射 |
| 跨层关联检索逻辑复杂 | Week 4 先看简单场景（单概念单表），再叠加复杂关联 |

---

## 七、依赖图

```
Week 1:  config.py → models.py → loader.py → indexer.py
                                              │
Week 2:                               concept.py → engine.py → matcher.py → ranker.py
                                                                             │
Week 3:                                                              pseudocode.py → cli.py
                                                                                    │
Week 4:                                                              联调 + 边界场景
                                                                                    │
Week 5:                                                              Streamlit + 打磨
```
