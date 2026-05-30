# Phase 4: Streamlit + LangSmith Design

> 2026-05-30 | Phase 4 | 基于 brainstorming 确认的设计

## 范围

Phase 4 聚焦两件事：**Streamlit WebUI**（面试展示核心）和 **LangSmith 全链路 trace**（面试加分项）。

## 架构

```
Streamlit UI (ui/app.py) → 复用已有模块，不重复造轮子
  - 页面1: 数据字典管理 → dictionary/loader + indexer
  - 页面2: 需求分析     → extractor + retrieval + generator
  - 页面3: 修复闭环     → testing + reconciliation/graph.py

LangSmith: 纯环境变量配置，不写代码
  LANGCHAIN_TRACING_V2=true
  LANGCHAIN_API_KEY=...
  LANGCHAIN_PROJECT=datapilot
```

## 文件变更

| 文件 | 动作 | 说明 |
|------|------|------|
| ui/app.py | 新增 | 三页 Streamlit 应用 |
| requirements.txt | 更新 | 加 streamlit |
| .env.example | 更新 | 加 LangSmith 配置 |
| CLAUDE.md | 更新 | 加 Streamlit 命令 |

## 页面设计

**页面1: 数据字典管理** — 上传 CSV/Excel → 预览 → 构建/重建 ChromaDB 索引
**页面2: 需求分析** — 输入需求 → 三步流水（概念提取 → 检索 → 伪代码）→ 可选生成 SQL
**页面3: 修复闭环** — 输入 SQL → 运行测试 → 实时展示每轮诊断+修复结果

## 错误处理

- 索引未构建 → 引导去页面1
- LLM 失败 → 显示错误，建议重试
- DB 未连接 → 降级展示诊断流程，跳过实际执行

## LangSmith

- 已有 Callbacks (TokenTracker + AuditLogger) 自动上报
- 可选：侧边栏显示配置状态指示灯
