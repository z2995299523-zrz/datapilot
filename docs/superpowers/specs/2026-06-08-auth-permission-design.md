# DataPilot 登录与权限控制模块 — 设计文档

> **目标**: 从零搭建登录认证 + 双维度数据权限控制（部门层级 × 业务条线）。
> 当前项目为 React + FastAPI 前后端分离架构，无任何认证机制。

## 1. 核心概念

### 两个权限维度

| 维度 | 控制粒度 | 作用阶段 |
|------|---------|---------|
| **部门层级**（组织架构树） | 数据行（ROW） | SQL 生成时注入 `WHERE dept_code IN (...)` |
| **业务条线**（business line） | 表/字段（TABLE/COLUMN） | 检索阶段过滤可见表 + SQL 生成时校验 |

两个维度取**交集**：用户只能看到「所在条线内」+「所在部门及下级」的数据。

### 角色模型

- **admin（系统管理员）**：可看全部数据 + 管理用户/部门/条线
- **普通用户**：按部门 + 条线限制数据范围

### 组织架构

- 任意深度的树形结构（总行 → 分行 → 支行 → 网点 …）
- 上级可见下级数据，平级不可见
- 使用**物化路径**（`path` 列 `LIKE` 前缀匹配）避免递归 CTE

## 2. 数据模型

### 2.1 数据库表（SQLite）

```sql
-- 部门表（树形结构，物化路径）
CREATE TABLE departments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,              -- "海淀支行"
    parent_id  INTEGER REFERENCES departments(id),
    path       TEXT NOT NULL UNIQUE,       -- "/总行/北京分行/海淀支行"
    level      INTEGER NOT NULL,          -- 层级深度，根=0
    is_active  INTEGER DEFAULT 1
);

-- 业务条线
CREATE TABLE business_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,             -- "零售银行"
    code        TEXT NOT NULL UNIQUE,      -- "retail"
    description TEXT DEFAULT '',
    is_active   INTEGER DEFAULT 1
);

-- 用户表
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,           -- bcrypt hash
    real_name     TEXT NOT NULL,
    department_id INTEGER REFERENCES departments(id),
    is_admin      INTEGER DEFAULT 0,
    is_active     INTEGER DEFAULT 1,
    created_at    TEXT DEFAULT (datetime('now'))
);

-- 用户-业务条线（多对多）
CREATE TABLE user_business_lines (
    user_id          INTEGER REFERENCES users(id),
    business_line_id INTEGER REFERENCES business_lines(id),
    PRIMARY KEY (user_id, business_line_id)
);

-- 表-业务条线
CREATE TABLE table_business_lines (
    table_name        TEXT NOT NULL,
    business_line_id  INTEGER REFERENCES business_lines(id),
    PRIMARY KEY (table_name, business_line_id)
);

-- 表-部门列映射（不同表用不同列名表示机构归属）
CREATE TABLE table_dept_columns (
    table_name  TEXT NOT NULL PRIMARY KEY,
    dept_column TEXT NOT NULL              -- "branch_code" / "org_id" / ...
);
```

### 2.2 种子数据

```yaml
部门:
  总行
  ├─ 北京分行 → 海淀支行, 朝阳支行
  ├─ 上海分行 → 浦东支行
  └─ 深圳分行

业务条线:
  零售银行(retail) | 对公银行(corporate) | AML反洗钱(aml) | 运营管理(ops)

默认管理员: admin / admin123 (首次启动强制修改密码)

表-条线示例:
  fact_transaction    → retail, corporate, aml
  fact_velocity       → aml
  v_customer_summary  → retail
  v_suspicious_transactions → aml

用户示例:
  zhangsan / 海淀支行 / retail+aml → 可查零售和反洗钱，仅海淀支行及下级数据
  admin   / 总行     / is_admin=1  → 可查全部
```

## 3. 架构

```
frontend/src/                          backend/
├── api/                               ├── routers/
│   ├── client.ts    [改] 加 token      │   ├── auth.py      [新] /api/auth/*
│   └── auth.ts      [新] login/me      │   ├── admin.py     [新] /api/admin/*
├── components/                        │   ├── analysis.py  [改] 注入权限
│   └── Layout.tsx   [改] 用户信息+登出   │   └── ...
├── pages/                             ├── auth.py           [新] JWT + Depends
│   ├── LoginPage.tsx      [新]         ├── main.py          [改] 注册路由
│   ├── AdminPage.tsx      [新]         └── schemas.py       [改] 加 auth schema
│   └── ...
├── auth/
│   └── AuthContext.tsx    [新] React context
└── App.tsx               [改] 路由守卫

auth/ (共享 Python 包，后端引用)
├── __init__.py
├── models.py     # SQLAlchemy ORM
├── database.py   # init_db, get_session, seed_data
└── security.py   # hash_password, verify_password, create_token, decode_token
```

## 4. 认证流程

### 4.1 登录时序

```
React LoginPage                FastAPI /api/auth/login           SQLite
      │                              │                            │
      │  POST {username, password}   │                            │
      │─────────────────────────────>│                            │
      │                              │  查 users                 │
      │                              │───────────────────────────>│
      │                              │  user row                 │
      │                              │<────────────────────────── │
      │                              │  bcrypt.verify(password)   │
      │                              │  查 departments (path +    │
      │                              │   子节点) + business_lines │
      │                              │  构建 permissions dict     │
      │                              │  签发 JWT (sub=user_id,    │
      │                              │    exp=8h, 含 permissions) │
      │  {token, user, permissions}  │                            │
      │<─────────────────────────────│                            │
      │                              │                            │
      │  localStorage.set('token')   │                            │
      │  React Router → /analysis    │                            │
```

### 4.2 请求认证

```
React (Axios interceptor)         FastAPI (auth.py dependency)
      │                                    │
      │  GET /api/analysis/full            │
      │  Authorization: Bearer <jwt>       │
      │───────────────────────────────────>│
      │                                    │  解码 JWT
      │                                    │  校验 exp
      │                                    │  提取 permissions
      │                                    │  → request.state.user
      │                                    │
      │  200 {concepts, retrieval, sql}    │
      │  (自动注入部门 WHERE,              │
      │   条线过滤可见表)                   │
      │<───────────────────────────────────│
      
      │  401 (token expired/invalid)       │
      │<───────────────────────────────────│
      │  Axios interceptor:                │
      │  clear token → redirect /login     │
```

### 4.3 JWT Payload 结构

```python
{
    "sub": 3,                        # user_id
    "username": "zhangsan",
    "real_name": "张三",
    "is_admin": False,
    "department_id": 15,
    "department_path": "/总行/北京分行/海淀支行",
    "visible_dept_ids": [15, 23, 24, 25],
    "business_line_codes": ["retail", "aml"],
    "exp": 1749386400,               # 8h from login
    "iat": 1749357600
}
```

## 5. 前端设计

### 5.1 路由结构

```
/login          → LoginPage        (无 Layout，全屏居中)
/dictionary     → DictionaryPage   (需登录)
/analysis       → AnalysisPage     (需登录)
/modeling       → ModelingPage     (需登录)
/reconciliation → ReconciliationPage (需登录)
/admin          → AdminPage        (需登录 + admin)
```

### 5.2 路由守卫

```typescript
// App.tsx
<BrowserRouter>
  <Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<ProtectedRoute />}>     {/* 检查 token 存在 */}
      <Route element={<AppLayout />}>        {/* 侧边栏 + Outlet */}
        <Route path="/dictionary" element={<DictionaryPage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        ...
        <Route element={<AdminRoute />}>     {/* 检查 is_admin */}
          <Route path="/admin" element={<AdminPage />} />
        </Route>
      </Route>
    </Route>
  </Routes>
</BrowserRouter>
```

### 5.3 LoginPage

- Ant Design `Form` + `Input` + `Button`
- 全屏居中，品牌 logo + "DataPilot" 标题
- 登录失败显示 `Alert` 错误信息
- 登录成功 → 存储 token 到 localStorage → `navigate('/dictionary')`
- 暗色主题一致

### 5.4 Layout 修改

侧边栏底部（原 ChromaDB 状态位置之上）新增用户信息区：

```
┌─────────────────┐
│  👤 张三         │
│  🏢 北京分行/海淀支行│
│  📊 零售银行, AML  │
│  [登出]          │
└─────────────────┘
```

admin 用户导航菜单多一项 `⚙ 系统管理`。

### 5.5 AuthContext

```typescript
// 轻量 Context，不引入 Redux
interface AuthState {
  token: string | null;
  user: User | null;
  permissions: Permissions | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  isAdmin: boolean;
}
```

### 5.6 Axios 拦截器

```typescript
// client.ts 修改
client.interceptors.request.use(config => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);
```

## 6. 后端设计

### 6.1 新增 API 端点

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/auth/login` | 无 | 用户名+密码 → JWT token + user info |
| GET | `/api/auth/me` | JWT | 返回当前用户 + permissions（用于刷新页面恢复状态） |
| GET | `/api/admin/users` | JWT+admin | 用户列表 |
| POST | `/api/admin/users` | JWT+admin | 创建用户 |
| PUT | `/api/admin/users/{id}` | JWT+admin | 修改用户（部门/条线/禁用/重置密码） |
| GET | `/api/admin/departments` | JWT+admin | 部门树 |
| POST | `/api/admin/departments` | JWT+admin | 添加部门 |
| PUT | `/api/admin/departments/{id}` | JWT+admin | 修改部门 |
| GET | `/api/admin/business-lines` | JWT+admin | 条线列表 |
| POST | `/api/admin/business-lines` | JWT+admin | 添加条线 |
| GET | `/api/admin/table-line-mappings` | JWT+admin | 表-条线映射列表 |
| POST | `/api/admin/table-line-mappings` | JWT+admin | 添加映射 |
| DELETE | `/api/admin/table-line-mappings/{table}/{line_id}` | JWT+admin | 删除映射 |

### 6.2 FastAPI 依赖注入

```python
# backend/auth.py

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """从 JWT 提取当前用户 permissions。所有需认证的路由共用。"""
    try:
        payload = jwt.decode(
            credentials.credentials,
            SECRET_KEY, algorithms=["HS256"]
        )
        return payload  # 包含 user_id, permissions 等
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的 Token")

async def require_admin(
    user: dict = Depends(get_current_user)
) -> dict:
    """仅 admin 可访问"""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
```

### 6.3 现有端点改造

所有 `/api/analysis/*`、`/api/modeling/*`、`/api/reconciliation/*`、`/api/dictionary/*` 的路由函数加 `user: dict = Depends(get_current_user))` 参数。

权限注入点：
- **检索阶段**：`engine.search()` 加 `visible_business_lines` 参数，只返回条线内的表
- **SQL 生成阶段**：`generate_sql_script()` 加 `user_permissions` 参数，注入部门 WHERE

### 6.4 FastAPI 应用修改 (`main.py`)

```python
# 注册新路由
from backend.routers import auth, admin
app.include_router(auth.router)
app.include_router(admin.router)

# 已有路由不变，但路由函数内部加 Depends(get_current_user)
```

## 7. 技术选型

| 组件 | 选择 | 原因 |
|------|------|------|
| 密码哈希 | `bcrypt` (4.1+) | 行业标准 |
| JWT | `PyJWT` (2.10+) | 轻量，纯 Python，FastAPI 官方推荐 |
| ORM | SQLAlchemy 2.x | 已在前端/后端分离前使用，兼容 SQLite/PostgreSQL |
| 数据库 | SQLite（默认）→ PostgreSQL（生产） | 零配置起步 |
| 部门树查询 | `WHERE path LIKE '/总行/北京分行/%'` | 一把查子节点，无递归 |
| 前端状态 | React Context + localStorage | 轻量，不引入 Redux |
| 路由守卫 | React Router v7 `<Outlet>` 嵌套路由 | 与现有 App.tsx 模式一致 |
| 前端组件 | Ant Design 6 Form/Table/Tree/Modal | 与现有 UI 一致 |

## 8. 依赖增量

```
# Python (requirements.txt)
bcrypt>=4.1.0
PyJWT>=2.10.0

# 前端 (package.json)
# 无新增 — Ant Design 6 已有 Form, Input, Table, Tree, Modal, message
```

## 9. 现有端点权限改造清单

| 端点 | 改造 |
|------|------|
| `POST /api/dictionary/upload` | `Depends(get_current_user)` |
| `GET /api/dictionary/status` | 公开（健康检查类） |
| `POST /api/analysis/full` | `Depends(get_current_user)` + 条线过滤 + 部门注入 |
| `POST /api/analysis/compare` | `Depends(get_current_user)` |
| `POST /api/reconciliation/run` | `Depends(get_current_user)` |
| `POST /api/reconciliation/tests` | `Depends(get_current_user)` |
| `POST /api/modeling/*` | `Depends(get_current_user)` |
| `GET /api/health` | 公开 |

## 10. 边界情况

| 场景 | 处理 |
|------|------|
| 首次启动，无用户表 | `init_db()` 自动建表 + `seed_data()` 创建 admin/admin123 |
| Token 过期 (8h) | Axios 拦截 401 → 清 token → 跳转 /login |
| 浏览器刷新 | `AuthContext` 从 localStorage 恢复 token，调 `GET /api/auth/me` 验证有效性 |
| 用户被禁用 | 登录时返回 403 "账号已被禁用"，不透露是否存在 |
| 用户所在部门被禁用 | 登录时返回 403 "部门已停用" |
| 用户无任何条线 | 可登录，但分析 API 返回空检索结果 + warning |
| 表未映射到任何条线 | 默认仅 admin 可见，普通用户检索不到 |
| 部门路径节点被删除 | 物化路径 LIKE 失效 → 子部门变孤儿 → admin 手动修复 |
| admin 用户忘记密码 | 通过 SQLite 直接重置（初期），后续加密码重置流程 |
| 旧 Streamlit UI (`ui/app.py`) | 不加认证，保留为开发调试入口 |

## 11. 测试策略

| 测试文件 | 覆盖 |
|---------|------|
| `tests/test_auth_security.py` | bcrypt hash/verify, JWT encode/decode, 过期 token |
| `tests/test_auth_models.py` | ORM 模型 CRUD、约束、部门树查询 |
| `tests/test_auth_api.py` | FastAPI TestClient: login/me/401/403/admin 端点 |
| `tests/test_auth_permission.py` | 条线过滤逻辑、部门子节点查询、权限交集 |
| `tests/test_auth_integration.py` | 带 token 的分析请求 → SQL 含部门 WHERE、检索仅可见表 |

## 12. 与现有功能的交互

- **数据血缘**: `TableInfo.source_system` 不受影响，与业务条线正交
- **LLM SQL 生成（待实现）**: `generate_sql_llm()` 同样接收 `user_permissions` 参数
- **修复闭环**: 修复后的 SQL 保留权限 WHERE 条件，不因修复而丢失过滤
- **CLI 模式**: 不加认证（本地开发工具），加 `--user` 参数可选指定用户身份测试权限
- **Streamlit 备用 UI**: 不加认证，保留为 dev-only

---

> **术语对照**: 部门层级 = Department Hierarchy | 业务条线 = Business Line | 物化路径 = Materialized Path | JWT = JSON Web Token | 路由守卫 = Route Guard
