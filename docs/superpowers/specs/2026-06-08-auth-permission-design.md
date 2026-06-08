# DataPilot 登录与权限控制模块 — 设计文档

> **目标**: 从零搭建登录认证 + 双维度数据权限控制（部门层级 × 业务条线）。
> 当前项目无任何认证机制，所有页面裸奔。

## 1. 核心概念

### 两个权限维度

| 维度 | 控制粒度 | 作用阶段 |
|------|---------|---------|
| **部门层级**（组织架构树） | 数据行（ROW） | SQL 生成时注入 `WHERE dept_code IN (...)` |
| **业务条线**（business line） | 表/字段（TABLE/COLUMN） | 检索阶段过滤可见表 + SQL 生成时校验 |

两个维度取**交集**：用户只能看到「所在条线内」+「所在部门及下级」的数据。

### 角色模型

- **admin（系统管理员）**：1 个或多个，可看全部数据 + 管理用户/部门/条线
- **普通用户**：按部门+条线限制数据范围

### 组织架构

- 任意深度的树形结构（总行 → 分行 → 支行 → 网点 …）
- 上级可见下级数据，平级不可见
- 使用**物化路径**（`path` 列 `LIKE` 前缀匹配）避免递归 CTE

## 2. 数据模型

### 2.1 数据库表设计（SQLite）

```sql
-- 部门表（树形结构，物化路径）
CREATE TABLE departments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,              -- 部门名称，如"海淀支行"
    parent_id  INTEGER REFERENCES departments(id),
    path       TEXT NOT NULL UNIQUE,       -- 物化路径 "/总行/北京分行/海淀支行"
    level      INTEGER NOT NULL,          -- 层级深度，根=0
    is_active  INTEGER DEFAULT 1
);

-- 业务条线
CREATE TABLE business_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,             -- 条线名称，如"零售银行"
    code        TEXT NOT NULL UNIQUE,      -- 条线代码，如"retail"
    description TEXT DEFAULT '',
    is_active   INTEGER DEFAULT 1
);

-- 用户表
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,    -- 登录账号
    password_hash TEXT NOT NULL,           -- bcrypt hash
    real_name     TEXT NOT NULL,           -- 真实姓名（显示用）
    department_id INTEGER REFERENCES departments(id),
    is_admin      INTEGER DEFAULT 0,       -- 1 = 系统管理员
    is_active     INTEGER DEFAULT 1,
    created_at    TEXT DEFAULT (datetime('now'))
);

-- 用户-业务条线（多对多）
CREATE TABLE user_business_lines (
    user_id          INTEGER REFERENCES users(id),
    business_line_id INTEGER REFERENCES business_lines(id),
    PRIMARY KEY (user_id, business_line_id)
);

-- 表-业务条线（哪些条线可以看哪些表）
CREATE TABLE table_business_lines (
    table_name        TEXT NOT NULL,
    business_line_id  INTEGER REFERENCES business_lines(id),
    PRIMARY KEY (table_name, business_line_id)
);
```

### 2.2 种子数据示例

```yaml
# 部门
总行
├─ 北京分行
│   ├─ 海淀支行
│   └─ 朝阳支行
├─ 上海分行
│   └─ 浦东支行
└─ 深圳分行

# 业务条线
零售银行 (retail) | 对公银行 (corporate) | AML反洗钱 (aml) | 运营管理 (ops)

# 表-条线映射
fact_transaction    → retail, corporate, aml
fact_velocity       → aml
v_customer_summary  → retail
v_suspicious_transactions → aml
dim_account         → retail, corporate, aml, ops

# 用户示例
zhangsan / 张三 / 海淀支行 / retail + aml → 可查零售和反洗钱，且只能看海淀支行及下级数据
admin   / 管理员 / 总行     / is_admin=1  → 可查全部
```

## 3. 架构

```
auth/
├── __init__.py        # 导出: init_db, login, logout, get_permissions, require_auth
├── models.py          # SQLAlchemy ORM（Department, BusinessLine, User, UserBusinessLine, TableBusinessLine）
├── database.py        # init_db(engine_url), get_session(), seed_data() 种子数据
└── session.py         # login(), logout(), get_current_user(), get_permissions(), require_auth()

ui/
├── app.py             # [修改] 注入登录 gate + 侧边栏用户信息 + 登出
├── pages/
│   ├── login.py       # [新建] 登录页组件
│   └── admin.py       # [新建] 管理页（用户/部门/条线/表映射 CRUD）
└── theme.py           # [不改]

generator/script.py    # [修改] SQL 生成末尾注入部门 WHERE 条件
retrieval/engine.py    # [修改] 检索时按条线过滤可见表
models.py              # [修改] TableInfo 加 business_lines: list[str]
config.py              # [修改] 加 AUTH_DB_URL
```

## 4. 权限判定流程

### 4.1 登录

```
用户输入 username + password
  → session.login(username, password)
    → 查 users 表，bcrypt.verify(password, password_hash)
    → 查 departments 表获取 path + 所有子部门 ID
    → 查 user_business_lines 获取条线代码列表
    → 返回 permissions dict
  → 写入 st.session_state.user + st.session_state.permissions
  → st.rerun() → 进入主页
```

### 4.2 permissions 结构

```python
{
    "user_id": 3,
    "username": "zhangsan",
    "real_name": "张三",
    "is_admin": False,
    # 维度 1: 部门层级 → 行级过滤
    "department_id": 15,
    "department_path": "/总行/北京分行/海淀支行",
    "visible_department_ids": [15, 23, 24, 25],
    # 维度 2: 业务条线 → 表级过滤
    "business_line_codes": ["retail", "aml"],
}
```

### 4.3 请求级权限注入

```
需求分析流程:
  1. 概念提取 (不变)
  2. 分层检索 → engine.search() 只检索 table_business_lines 中当前条线可看的表
  3. 伪代码生成 (不变)
  4. SQL 生成 → 条目线校验 + 注入部门 WHERE:
     WHERE ... AND t.dept_code IN ('总行', '北京分行', '海淀支行', '海淀支行-网点A')
     -- 或通过 JOIN department 表过滤
```

### 4.4 部门 → SQL 列映射

不同表用不同列名表示机构归属（`branch_code` / `dept_id` / `org_code` 等），需要一个映射表：

```sql
CREATE TABLE table_dept_columns (
    table_name   TEXT NOT NULL PRIMARY KEY,
    dept_column  TEXT NOT NULL              -- 该表中表示机构归属的列名
);

-- 示例
INSERT INTO table_dept_columns VALUES
    ('fact_transaction',  'branch_code'),
    ('v_customer_summary', 'branch_code'),
    ('dim_account',       'org_id');
```

SQL 生成时据此注入过滤条件：
```sql
-- 原: SELECT * FROM fact_transaction WHERE amount > 10000
-- 后: SELECT * FROM fact_transaction WHERE amount > 10000
--       AND branch_code IN ('BJ001', 'BJ001-HD', 'BJ001-HD-001')
```

若某表未在 `table_dept_columns` 中注册，则**不注入部门过滤**（仅靠条线限界），相当于该表的数据行对所有部门可见。

### 4.5 完整权限判定流程

```
需求分析请求
  → 检索: engine.search(concepts, visible_lines=user.business_line_codes)
         → 只返回 table_business_lines 中当前用户条线可看的表
  → 伪代码生成 (不变)
  → SQL 生成:
     1. 校验所有引用的表都在用户条线范围内
     2. 查 table_dept_columns 获取 dept_column
     3. 注入: WHERE ... AND dept_column IN (user.visible_dept_codes)
```

## 5. Streamlit 登录流程

```
st.session_state.user 存在?
├─ 否 → 显示 login_page()
│       └─ 登录成功 → session_state.user = {...}
│                     → st.rerun()
└─ 是 → 侧边栏显示:
        用户名: 张三
        部门: 北京分行/海淀支行
        条线: 零售银行, AML反洗钱
        [登出] 按钮
       
        ── 导航 ──
        📚 数据字典管理
        🔍 需求分析
        🔧 修复闭环
        ⚙ 系统管理  (仅 is_admin=True 时显示)
```

## 6. 管理页面功能（admin only）

| Tab | 功能 | CRUD |
|-----|------|------|
| 用户管理 | 用户列表、新建用户、禁用/启用、重置密码、分配部门+条线 | Create, Read, Update |
| 部门管理 | 部门树展示、添加子部门、重命名、禁用（不物理删除） | Create, Read, Update |
| 条线管理 | 条线列表、新建条线、编辑描述、禁用 | Create, Read, Update |
| 表-条线映射 | 表格展示、添加映射、删除映射 | Create, Read, Delete |

## 7. 技术选型

| 组件 | 选择 | 原因 |
|------|------|------|
| 密码哈希 | `bcrypt` (4.0+) | 行业标准，Python 库无外部依赖 |
| ORM | SQLAlchemy 2.x | Streamlit 常用，支持 SQLite/PostgreSQL 切换 |
| 数据库 | SQLite（默认）→ PostgreSQL（生产） | SQLite 零配置，物化路径 LIKE 兼容两者 |
| 部门树查询 | `WHERE path LIKE '/总行/北京分行/%'` | 一次查询取出所有子节点，避免递归 CTE |
| 会话 | `st.session_state` | Streamlit 原生机制，每 tab 一个 session |
| 登录页 | `st.empty()` + container | 覆盖全屏，不依赖多页路由 |

## 8. 依赖增量

```
# 新增依赖
bcrypt>=4.0.0
sqlalchemy>=2.0.0

# 无新增依赖（如果已有 sqlalchemy 则不需要）
```

## 9. 边界情况

| 场景 | 处理 |
|------|------|
| 首次启动，无用户表 | `init_db()` 自动建表 + `seed_data()` 创建 admin/admin 默认账号 |
| 用户被禁用 | 登录时报"账号已被禁用"，不透露是否存在 |
| 用户所在部门被禁用 | 登录时报"部门已停用，请联系管理员" |
| 用户无任何条线 | 可登录但检索结果为空，提示"未分配业务条线权限" |
| 表未映射到任何条线 | 默认仅 admin 可见，普通用户不可见 |
| 部门路径中某个节点被删除 | 物化路径 LIKE 查询自动失效，子部门变为孤儿 → admin 需手动修复 |
| 多个 admin | 支持，所有 admin 权限相同 |

## 10. 测试策略

| 测试文件 | 覆盖 |
|---------|------|
| `tests/test_auth_models.py` | ORM 模型创建、约束、关系 |
| `tests/test_auth_session.py` | login/logout/get_permissions/密码验证 |
| `tests/test_auth_permission.py` | 条线过滤、部门子节点查询、权限交集 |
| `tests/test_auth_integration.py` | SQL 注入部门 WHERE、检索过滤可见表 |
| `tests/test_auth_security.py` | bcrypt 验证、禁用用户、SQL 注入防护 |

## 11. 与现有功能的交互

- **数据血缘（已实现）**: `TableInfo.source_system` 不受影响，两个维度正交
- **LLM SQL 生成（待实现）**: `generate_sql_llm()` 同样接入权限过滤，与规则引擎 fallback 一致
- **修复闭环**: 诊断/修复不涉及数据权限变更，只需保证修复后的 SQL 保留权限 WHERE 条件
- **CLI 模式**: CLI 不强制登录，加 `--user` 参数可选指定用户身份来测试权限

---

> **术语对照**: 部门层级 = Department Hierarchy | 业务条线 = Business Line | 物化路径 = Materialized Path | 数据血缘 = Data Lineage
