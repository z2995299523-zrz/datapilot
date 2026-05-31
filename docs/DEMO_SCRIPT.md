# DataPilot Demo 演示脚本

> 面试展示用 | 预计 15-20 分钟 | 3 个场景 + 技术亮点

---

## 准备清单

- [ ] `DEEPSEEK_API_KEY` 已设置
- [ ] 已构建索引 `python -m dictionary.indexer demo/data_dict.csv`
- [ ] 打开终端：`streamlit run ui/app.py`
- [ ] 浏览器打开 `http://localhost:8501`
- [ ] LangSmith 仪表板（可选）：展示 trace 追踪

---

## 场景 1: 需求分析全链路（5 分钟）

**话术**: "DataPilot 的核心链路是：输入业务需求 → 自动生成 SQL → 自动测试 → 自动修复。"

### 操作步骤

1. **页面：数据字典管理**
   - 展示已构建的索引状态（54 条记录）
   - 话术："数据字典是所有下游的基础，用 ChromaDB + BGE 中文语义模型做向量化。"

2. **页面：需求分析**
   - 粘贴 `demo/req_sample.txt` 内容
   - 点击「开始分析」
   - 展示三步流水线展开：
     - Step 1: 提取的业务概念（实体/维度/指标/条件）
     - Step 2: 分层检索结果（DM/DWS/ODS 递进匹配）
     - Step 3: 伪代码 → SQL 生成

3. **技术亮点**:
   - "概念提取走 LangChain LCEL 链，PydanticOutputParser 自动校验"
   - "SQL 生成走规则引擎，不依赖 LLM，确保语法确定性"
   - "分层检索：DM → DWS → ODS，先聚合层后明细层"

---

## 场景 2: 修复闭环（5 分钟）

**话术**: "SQL 生成后不是终点，DataPilot 会做三层测试，失败了自动诊断修复。"

### 操作步骤

1. **页面：修复闭环**
   - 输入一段 SQL（手动构造或使用场景1生成的结果）
   - 不连接数据库时：展示诊断流程预览
   - 话术："没连数据库时可以看到将执行的检查项：L1 基础质量、L2 逻辑比对、L3 诊断。"

2. **如果连接了 SQLite/MySQL**:
   - 填写连接字符串 → 点击运行
   - 展示每轮修复结果展开：
     - 第 1 轮：发现问题 → 自动修复 → 重测
     - 第 2 轮：通过或继续修复
   - 最多 3 轮循环

3. **技术亮点**:
   - "修复闭环用 LangGraph StateGraph，条件路由显式声明"
   - "五级诊断链路：数据源 → 码值 → JOIN → 口径 → 概念遗漏"
   - "可自动修复项：码值替换、CAST 转换、补充 WHERE；不可修复的生成人工报告"

---

## 场景 3: 端到端完整流程（5 分钟）

**话术**: "下面展示从零到一的完整流程。"

### 操作步骤

1. 上传自定义数据字典（模拟真实项目）
2. 构建/重建索引
3. 输入自定义需求
4. 完整链路 → 生成 SQL
5. （可选）运行测试修复闭环

---

## 面试话术速查

| 技术 | 一句话 |
|------|--------|
| **LangGraph** | "修复闭环不是藏在 if/else 里，是显式的图边声明，checkpointer 可审计追溯" |
| **LangChain** | "PromptTemplate 集中管理 + PydanticOutputParser 自动校验 + LCEL 声明式链" |
| **ChromaDB** | "DM/DWS/ODS 三层 metadata 过滤 + BGE 中文语义匹配" |
| **Pydantic** | "全链路数据契约，从概念到 SQL 到测试报告，类型安全" |
| **LLM 工程化** | "每次 LLM 调用 3 次 retry + token 追踪 + 审计日志 + LangSmith trace" |
| **规则引擎 SQL** | "SQL 用规则引擎生成，不受 LLM 不稳定影响，语法确定" |
| **Streamlit** | "三页 WebUI，复用已有模块，页面间零耦合" |

---

## 常见面试追问

**Q: 为什么不用 Agent 框架？**
A: "我们这个场景步骤固定（DM→DWS→ODS 不可绕过），是 Workflow Engine 不是 Autonomous Agent。框架用在真正需要的地方——修复闭环的 LangGraph 就是精准场景。"

**Q: LLM 生成 SQL 不稳定怎么办？**
A: "SQL 不靠 LLM 生成，靠规则引擎——PseudoCodeStep 到 SQL 子句的确定性映射。LLM 只做概念理解和伪代码，SQL 是 100% 确定性的。"

**Q: 修复成功率如何？**
A: "L1 基础质量（码值/空值/超长）可自动修复，L2 逻辑比对可定位偏差，L3 五级诊断区分可自动和需人工确认的问题。不可修复的生成明确的人工确认报告。"

**Q: 怎么保证 LLM 输出格式？**
A: "PydanticOutputParser 自动校验 + 3 次 retry + 失败降级到规则引擎。不乐观解析，不假设 LLM 输出正确。"
