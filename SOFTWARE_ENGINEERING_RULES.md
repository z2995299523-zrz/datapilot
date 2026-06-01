# 软件工程开发规范 v2.0

> 适用: 所有项目、所有语言、所有规模
> 性质: 绝对规范 — 与项目级 CLAUDE.md 中的"最小扩散"原则同级，架构决策时本规范优先
> 维护: 张润泽 + HermesAgent, 2026-06-01

---

## 零、核心信念

**代码是负债，不是资产。** 每多一行代码，就多一行需要测试、理解、维护的东西。写代码的唯一正当理由，是它现在解决了某个真实问题。

**可测试性是架构质量的唯一客观指标。** 如果一个设计让你写测试时痛苦——需要 mock 全局状态、需要启动整个系统、需要按特定顺序执行——不是测试框架的问题，是架构的问题。

**显式胜过隐式。** 全局状态隐式传递依赖。配置文件隐式耦合模块。继承隐式绑定行为。能用参数就参数，能用组合就组合，能写出来就不藏在背后。

---

## 一、设计原则（SOLID + 两条补充）

### 1.1 单一职责 (SRP)

一个模块/类/函数只有一个理由需要修改。

```
判断标准:
  "这个模块做什么？" 
  → 如果回答里有"和"字, 拆成两个模块。

  ❌ "检索和码值翻译"
  ✅ "检索: 在数据字典中查找匹配的表和字段"
  ✅ "断言翻译: 把码值映射翻译成 SQL WHERE 条件"
```

### 1.2 开闭原则 (OCP)

对扩展开放，对修改关闭。

```
判断标准:
  加一个新功能, 需要改已有模块的内部代码吗？
  ❌ 加一个新的 LLM provider → 要改 Pipeline 里的 if/else
  ✅ 加一个新的 LLM provider → 实现 LLMClient 接口, Pipeline 不动
```

### 1.3 里氏替换 (LSP)

子类/实现可以替换父类/接口，程序行为不变。

```
判断标准:
  一个 Protocol 的实现, 替换成另一个实现后, 调用方能正常工作吗？
  ❌ OpenAI 实现返回 dict, DeepSeek 实现返回 list → 调用方崩
  ✅ 两个实现都返回 AgentOutput, 内部结构不同但接口一致
```

### 1.4 接口隔离 (ISP)

不该强迫调用方依赖它不需要的方法。

```
判断标准:
  一个接口/Protocol 定义了 10 个方法, 但实际调用方只用其中 3 个
  → 拆成 3 个小接口。
  
  ❌ class Agent(Protocol):
        def think(...): ...
        def act(...): ...
        def observe(...): ...
        def save_memory(...): ...  ← 只有 Supervisor 需要

  ✅ class Thinker(Protocol):
        def think(...): ...
     class Actor(Protocol):  
        def act(...): ...
     class MemoryManager(Protocol):
        def save_memory(...): ...
```

### 1.5 依赖倒置 (DIP)

高层不依赖低层，两者都依赖抽象。**抽象的定义权属于高层。**

```
判断标准:
  依赖方向是从"策略"指向"细节", 还是反过来？

  ❌ 报表逻辑(策略) import Oracle连接器(细节)
     → 换数据库 → 改报表代码 (高层因为低层的变化而改动)

  ✅ 报表逻辑(策略) 定义 DataSource 接口
     Oracle连接器(细节) 实现 DataSource 接口
     SQLServer连接器(细节) 也实现 DataSource 接口
     → 换数据库 → 只换注入的实现, 报表代码不动
```

### 1.6 组合优于继承

能用"有一个"解决的问题，不用"是一个"。

```
判断标准:
  你是想复用代码, 还是想表达"X 是 Y 的一种"？

  ✅ 复用代码: 用组合 (把共享逻辑提取为独立对象, 注入)
     class ReportGenerator:
         def __init__(self, formatter: Formatter): ...

  ✅ 表达层级关系: 用继承 (有限制地)
     class PDFFormatter(Formatter): ...   ← 合理
     
  ❌ 为了复用几行代码搞 3 层继承
     class BaseHandler -> DataHandler -> CustomerDataHandler
     → 3 个月后谁也看不懂 handler 里哪行代码从哪个父类来的
```

### 1.7 YAGNI (You Aren't Gonna Need It)

不为"以后可能需要"写代码。

```
判断标准:
  删掉这段代码, 当前功能还完整吗？
  ✅ 完整 → 删掉
  ❌ 不完整 → 保留

  ❌ "以后可能要支持 PostgreSQL, 先加个 dialect 参数" → 不加
  ✅ 真实需求来了: "现在要支持 PostgreSQL" → 重构并加参数
```

---

## 二、模块设计

### 2.1 模块边界

模块 = 一组高内聚的代码，通过明确的接口与外界通信。

```
内聚性判断:
  高内聚: 模块内的所有代码围绕同一个核心职责
     ✅ retrieval/: 所有代码都在做"查找匹配的表和字段"
  
  低内聚: 模块内的代码处理多个不相关的职责
     ❌ utils.py: 包含日期格式化 + SQL 生成 + 文件读取 + 日志
```

### 2.2 模块间通信

模块之间不直接依赖具体实现，依赖接口/契约。

```
通信方式选择:
  同步调用 → 接口(Protocol/Interface/ABC) + 依赖注入
  异步通知 → 事件/消息队列
  数据共享 → 通过参数传递, 不通过全局变量
```

### 2.3 循环依赖

**零容忍。** 发现立即修复。

```
检测方法:
  A import B
  B import A (或 B import C import A)
  → 循环依赖

修复方法 (按优先级):
  1. 提取共同依赖到 C, A 和 B 都依赖 C
  2. 合并 A 和 B (如果它们逻辑上本就是一个模块)
  3. 用依赖注入打破编译期循环 (A 依赖 B 的接口, B 在运行时注入)
```

### 2.4 模块可见性

一个模块暴露的公开 API 越小越好。

```
判断标准:
  __init__.py 里显式列出了哪些符号？
  → 越少越好。不列在 __init__.py 里的就是内部实现, 可以随意改。

  ✅ __init__.py: [search, RetrievalEngine]   ← 只有 2 个公开 API
  ❌ __init__.py: [search, match, rank, load, save, clean, ...] ← 太多
```

---

## 三、依赖管理

### 3.1 依赖获取方式

```
优先级从高到低:

1. 构造器注入 (最优)
   class Service:
       def __init__(self, dependency: DependencyProtocol):
           self.dep = dependency
   → 依赖在创建时确定, 不可变, 容易测试

2. 方法参数注入
   def process(data, dependency: DependencyProtocol):
       ...
   → 每次调用可能用不同实现

3. 工厂/容器获取
   container.get("dependency")
   → 集中管理, 但调用方仍然"主动查找"

4. 全局变量 / 单例模式 (最差)
   GLOBAL_CONFIG = ...
   → 隐式耦合, 不能并行测试
```

### 3.2 依赖方向规则

```
允许的依赖方向:
  业务逻辑 → 基础设施接口
  编排层 → 具体实现
  高层策略 → 抽象定义

禁止的依赖方向:
  基础设施实现 → 业务逻辑
  具体实现 → 编排层
  A → B 且 B → A (循环)
  任何模块 → 全局配置对象 (config 应该注入, 不 import)
```

### 3.3 第三方库依赖

```
规则:
  1. 能用一个库解决的, 不用两个
  2. 第三方库通过适配器层隔离 (不直接在业务逻辑里 import)
  3. 选库标准: 活跃维护 > Star 数 > 文档质量 > 性能

适配器示例:
  ✅ business/analyzer.py → adapters/llm_client.py → openai/httpx
     (业务逻辑只知道 LLMClient 接口, 不知道底层用的是 openai 还是 httpx)
  
  ❌ business/analyzer.py → import openai
     (换 LLM provider 要改业务逻辑)
```

---

## 四、接口与契约

### 4.1 何时定义接口

```
必须定义接口:
  - 两个独立模块之间通信
  - 有多种实现需要替换 (不同 LLM provider, 不同数据库)
  - 需要 mock 做测试

不需要定义接口:
  - 只有一个实现, 且未来不会替换
  - 纯数据对象 (DTO/Value Object)
  - 仅模块内部使用的辅助类
```

### 4.2 接口设计原则

```
1. 接口属于调用方, 不属于实现方
   → 谁用接口, 谁定义接口的形状

2. 接口尽可能小
   → 一个接口 3-5 个方法最好, 超过 10 个考虑拆分

3. 接口命名以"做什么"为前缀, 不是"是什么"
   ✅ DataFetcher, ReportGenerator, MessageSender
   ❌ IDataService, DataManager, DataHandler (太泛)
```

### 4.3 数据结构传递

```
优先:   不可变数据结构 (dataclass/frozen, namedtuple, record)
可用:   可变对象 (需要明确标注谁可以修改)
避免:   裸 dict/list 跨模块传递
禁止:   用字符串 key 在模块间传递结构化数据

示例:
  ❌ def handle(data: dict):
         name = data["name"]  # 如果上游改了 key 名, 这里静默出错
  
  ✅ @dataclass(frozen=True)
     class UserInput:
         name: str
         age: int
     def handle(input: UserInput):
         name = input.name  # 有类型检查, IDE 自动补全
```

---

## 五、错误处理

### 5.1 错误分类

```
可恢复错误:   重试后可能成功 (网络超时, API rate limit)
可降级错误:   用备用方案 (LLM 不可用 → 规则引擎)
需人工错误:   必须人介入 (数据校验不通过)
致命错误:     不可恢复, 应快速失败并告警
```

### 5.2 错误处理策略

```
每一处可能失败的操作, 必须显式处理:

1. 先判断能否重试
   → 指数退避 + 最大重试次数 + jitter

2. 不能重试则判断能否降级
   → LLM 调用失败 → 规则引擎
   → 主数据库不可用 → 缓存数据

3. 不能降级则判断能否快速失败
   → 把错误信息 + 上下文打包返回
   → 不吞异常, 不返回 null/空列表假装没问题

4. 绝对不能:
   except Exception: pass          ← 吞异常
   except: return []               ← 返回假数据
   try: ... except: raise "error"  ← 丢失原始堆栈
```

### 5.3 错误传播

```
跨模块边界: 抛自定义异常, 包含足够上下文
  raise DataRetrievalError(table="customer", query=sql, cause=e)

模块内部:   可以直接抛, 但在边界处包装
  try:
      raw = db.execute(sql)
  except DBError as e:
      raise DataRetrievalError(...) from e  ← 保留原始堆栈
```

---

## 六、测试策略

### 6.1 测试分层

```
         /\
        /E2E\         少量: 核心用户流程
       /------\
      /集成测试\       中等: 模块间交互
     /----------\
    /  单元测试   \     大量: 单个函数/类
   /--------------\
```

### 6.2 测试原则

```
1. 测试行为, 不测试实现
   ✅ 测试: 输入 X → 输出 Y
   ❌ 测试: 内部调用了 method_a() 再调 method_b()

2. 一个测试只测一件事
   ✅ test_returns_empty_list_when_no_match()
   ❌ test_search_works()  ← 太模糊

3. 测试应该能独立运行, 不依赖执行顺序
   ✅ 每个测试创建自己的 fixture
   ❌ test_b 依赖 test_a 设置的全局状态

4. Mock 的层级反映架构的耦合度
   ✅ 只需 mock 接口 (Protocol)
   ❌ 需要 mock 全局变量 → 说明架构紧耦合
```

### 6.3 可测试性检查

```
一个模块可测试 = 不依赖以下任何东西就能单独运行:
  - 环境变量
  - 全局配置对象
  - 数据库连接
  - 网络
  - 文件系统
  - 其他模块的具体实现
  - 执行顺序

如果必须依赖其中某项, 用接口隔离:
   ✅ 数据库 → DBConnection Protocol → 测试时注入内存实现
   ✅ 网络   → HTTPClient Protocol   → 测试时注入 mock
   ✅ 文件   → FileSystem Protocol   → 测试时注入内存实现
```

---

## 七、命名

### 7.1 通用原则

```
1. 揭示意图: 名字应该回答"做什么", 而不是"怎么做"
   ✅ calculate_monthly_revenue()
   ❌ process_data_v2()

2. 长度与作用域成正比
   全局可见: 长描述性名称
   局部变量: 短名称可接受 (i, x, df)

3. 避免噪音词
   ❌ DataManager, DataHandler, DataProcessor, DataService
   → 这四个区别是什么? 没人知道
```

### 7.2 按类型命名规范

```
类/接口:   名词, 描述"是什么"
  ✅ CustomerReport, LLMClient, DatabaseConnection
  ❌ CustomerManager, DataProcessor

函数/方法: 动词+名词, 描述"做什么"
  ✅ generate_report(), search_by_name()
  ❌ report(), search()  ← 太模糊

布尔值:    以 is/has/can/should 开头
  ✅ is_active, has_errors, can_retry
  ❌ active, error_flag, retry

集合:      复数名词
  ✅ customers, error_messages
  ❌ customer_list, error_arr  ← 类型噪音
```

---

## 八、注释与文档

### 8.1 注释原则

```
不写注释的最佳方式是把代码写成不需要注释。

需要写注释 = 代码本身表达力不够。

什么需要注释:
  ✅ 为什么这样做 (决策背景、权衡)
     # 用正则不用 sqlparse: sqlparse 对窗口函数支持有限
     # 见 issue #42

  ✅ 非显而易见的边界条件
     # trade_date 可能为 0000-00-00 (MySQL 默认值)

  ❌ 解释代码在做什么 (重构代码让它自解释)
     # 遍历每个客户, 计算交易总额
     for customer in customers:           ← 废话, 代码已经说了
         total += customer.amount

  ❌ 过期的注释 (比没注释更危险)
     # v1.2: 支持 Oracle → 实际代码早就去掉了 Oracle 支持
```

### 8.2 文档分层

```
README.md:      项目是什么 + 怎么跑起来 (< 5 分钟读完)
ARCHITECTURE.md: 系统架构 + 核心设计决策 (可选, 规模 > 10 个模块时必须有)
CLAUDE.md:       AI 编码助手的上下文 (命令 + 约束 + 当前状态)
docstrings:      公开 API 的契约 (输入/输出/异常)
行内注释:        为什么这样做 (决策 + 边界条件)
```

---

## 九、重构

### 9.1 重构 vs 重写

```
重构: 不改外部行为, 只改内部结构
重写: 扔掉旧的, 从零写新的

优先重构, 避免重写。重写的成功率远低于预期。
```

### 9.2 重构触发条件

```
立即重构:
  - 循环依赖
  - 同一个知识在 3 处以上重复
  - 模块超过 500 行
  - 函数超过 50 行
  - 测试需要 mock 全局状态才能跑

计划重构:
  - 加新功能前发现现有设计阻碍
  - 一个模块被 5+ 个其他模块依赖 (瓶颈模块)
  - 性能瓶颈无法通过局部优化解决
```

### 9.3 重构安全准则

```
1. 每次只做一种重构
   改依赖注入就只改注入, 不同时改业务逻辑

2. 重构前后行为一致
   用测试证明: 重构前通过 → 重构后也通过

3. 先加新接口, 再删旧接口
   旧代码标记 deprecated → 确认所有调用方已迁移 → 删除

4. 如果重构超过 2 小时还没看到尽头
   停下来, 重新评估方案。可能选错了方向。
```

---

## 十、性能

### 10.1 性能优化时机

```
1. 先让代码正确, 再让代码快
2. 用 profiler 找到真正的瓶颈, 不凭直觉优化
3. 优化最慢的 20% 通常能解决 80% 的问题

常见"伪优化"(做了也没用):
  ❌ 不用现成库自己写算法
  ❌ 把 I/O 密集操作改成多线程 (GIL)
  ❌ 在循环里 micro-optimize (正确的做法是把 I/O 异步化)
```

### 10.2 资源管理

```
所有外部资源必须显式释放:
  - 数据库连接 → 连接池, 用完归还
  - 文件句柄   → with 语句, 自动关闭
  - 网络连接   → 设置超时, 用完关闭
  - 内存       → 流式处理替代全量加载

反模式:
  ❌ 全局数据库连接 (不知道什么时候关, 谁在用)
  ❌ 加载整个文件到内存再处理 (100MB CSV → OOM)
```

---

## 十一、安全

### 11.1 最小权限

```
代码应该只访问它需要的:
  - Agent 执行 SQL → 只有 SELECT 权限, 没有 DROP
  - 模块访问文件 → 只读访问, 不写
  - API Key → 只传给需要的模块, 不放进全局变量
```

### 11.2 输入校验

```
所有外部输入必须在边界处校验:
  - 用户输入 → 长度限制 + 类型校验 + 格式校验
  - LLM 输出 → Pydantic 校验 + 业务规则校验
  - API 返回 → 状态码检查 + schema 校验
  - 文件内容 → 大小限制 + 格式校验 + 恶意内容检测

绝对禁止:
  ❌ 直接把用户输入拼接到 SQL (SQL 注入)
  ❌ 直接把 LLM 输出当作可执行代码
  ❌ 信任文件名为用户提供的字符串
```

---

## 十二、版本控制

### 12.1 Commit 规范

```
一个 commit = 一个逻辑变更

✅ Add: 概念提取的 LLM Prompt
✅ Fix: 空值率计算遗漏 NULL 行
✅ Refactor: 把 chat_json 改为构造器注入

❌ "改了一些东西"
❌ 一个 commit 包含功能 + 重构 + 格式化 (无法单独回滚)
```

### 12.2 分支策略

```
main:      可部署的稳定版本
feature/*: 功能开发分支
fix/*:     修复分支
refactor/*:重构分支

合并到 main 前:
  - 所有测试通过
  - 没有冲突
  - 代码审查通过
```

---

## 十三、技术选型

```
选库/框架/工具的标准 (按优先级):

1. 社区活跃度
   → 最近 3 个月有 commit / 有活跃 issue 讨论 / 不是单人维护

2. 是否还在维护
   → 1 年内没有 release → 视为已死

3. 与你现有技术栈的契合度
   → 用同一种范式、同一种生态, 降低认知负担

4. 文档质量
   → 有完整 API 文档 + 有代码示例 + 有错误处理说明

5. 性能
   → 只在确实需要时才作为选型标准
```

---

## 十四、持续改进

这份规范本身就是活文档。当出现以下情况时更新：

```
触发更新:
  - 被同一个坑绊倒两次 → 加进规范防止第三次
  - 发现规范有遗漏 → 补充
  - 规范中的建议在实践中证明不可行 → 修改
  - 学了新东西后发现旧规范不够好 → 升级版本号
```
