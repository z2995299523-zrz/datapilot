# DataPilot 架构重构命令

> 执行者: Claude Code
> 前置: 必须读 `SOFTWARE_ENGINEERING_RULES.md` + `agentflow-dev` skill + `datapilot-dev` skill
> 性质: 原则驱动 — 不提供步骤清单, 提供约束和目标, 由你自主发现问题并修复

---

## 目标

把 DataPilot 从当前的紧耦合状态重构为符合 `SOFTWARE_ENGINEERING_RULES.md` 的架构。

---

## 约束

### 不可违反

1. **不改功能** — 所有现有 292 tests 必须在重构后仍然通过。`python cli.py analyze --req demo/req_sample.txt` 必须输出相同结果。

2. **渐进式** — 每次只改一个关注点。改完跑测试。通过再继续。不能一次性重构全部 47 个文件。

3. **保留兼容层** — 旧接口标记 `# Deprecated` 保留, 不要直接删除。确保现有调用方不中断。

4. **不碰以下目录** — 它们有各自的原因暂不参与本次重构:
   - `reconciliation/` — 等 P2 3-Agent 架构时整体重构
   - `ui/` — Streamlit 有自己的状态管理
   - `dictionary/loader.py` — 纯解析器, 不依赖全局状态
   - `demo/` — 演示数据

---

## 你需要自主完成的事

### 1. 诊断 — 发现紧耦合

通读项目代码, 找出所有违反以下原则的地方:

- 模块通过 `from config import XXX` 获取配置值 (应通过构造器参数)
- 模块内部 `_client = None` 做模块级单例 hack (应由容器管理)
- 模块之间传裸 dict, 接收方用 `["key"]` 取值 (应定义 Protocol 或 Pydantic)
- `import` 链中存在循环 (A import B, B import C, C import A)
- 一个模块做了两件不相关的事 (单一职责原则)

**输出**: 列出你发现的所有问题, 标注严重程度和影响范围。让用户确认后再动手。

### 2. 设计 — 提出重构方案

为发现的问题设计修复方案。方案必须:

- 符合依赖倒置原则: 高层定义接口, 低层实现接口
- 让被重构的模块可以独立 import (不依赖 config.py)
- 让被重构的模块可以独立测试 (不需要 mock 全局状态)
- 给出接口/类的命名和职责描述

**输出**: 方案概述。让用户确认后再动手。

### 3. 执行 — 逐个重构

每次只重构一个关注点。顺序你自己决定, 但必须遵循:

- 先建基础设施 (接口定义、容器), 再迁移调用方
- 每次改动后跑 `pytest tests/ -v`
- 测试失败 → 停下来修, 不带着失败继续
- 兼容层保留, 所有测试通过后再标记 deprecated

### 4. 验证 — 证明重构正确

重构完成后:

- 证明每个模块的耦合度降低了: 展示重构前后的 `import` 链变化
- 证明可测试性提高了: 选一个核心模块, 展示重构前后的测试写法对比
- 证明没有引入循环依赖
- 证明 `cli.py analyze` 的输出与重构前一致

---

## 补充上下文

以下是已知的项目痛点, 但你可能会发现更多:

- `config.py` 被几乎所有文件 import, 且包含副作用 (mkdir, load_dotenv)
- `llm_client.py` 用模块级 `_client = None` 做单例
- `cli.py` 最顶部必须预加载 BGE 模型, 绕过 config→embedding 的循环导入
- `extractor/concept.py` 和 `generator/pseudocode.py` 的 LLM 调用格式完全相同但各自实现
- BGE embedding 在 indexer.py 和 matcher.py 各加载一次 (CLAUDE.md 已标注此问题)

---

## 停止条件

如果遇到以下情况, 停下来问用户:

- 重构后的测试失败, 但原因不在你改的代码里 (发现已有 bug)
- 某个模块的耦合是"故意的" (有其他约束你不知道)
- 你发现一个更根本的架构问题, 不在本次重构范围但值得讨论
- 重构进行了 2 小时还没看到清晰的终点
