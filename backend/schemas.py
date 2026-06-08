"""
API 请求/响应 Schema 定义

复用 models.py 中的 Pydantic 模型作为响应体。
此处仅定义 API 层特有的请求体。
"""

from pydantic import BaseModel, Field


# ── 分析 ────────────────────────────────────────────────

class AnalysisRequest(BaseModel):
    """全链路需求分析请求"""
    requirement_text: str = Field(..., description="业务需求文档全文")
    generate_sql: bool = Field(True, description="是否生成 SQL 脚本")
    dict_path: str | None = Field(None, description="数据字典文件路径，留空用 demo 默认")


# ── 修复闭环 ────────────────────────────────────────────

class ReconciliationRunRequest(BaseModel):
    """修复闭环完整请求"""
    original_sql: str = Field(..., description="待测试的 SQL 查询")
    requirement_text: str = Field("", description="原始需求文档（可选）")
    db_conn_str: str = Field("", description="数据库连接字符串")
    max_loops: int = Field(3, ge=1, le=10, description="最大重试次数")
    dict_path: str | None = Field(None, description="数据字典文件路径")
    expected_csv_path: str | None = Field(None, description="预期结果 CSV 路径（可选）")


class ReconciliationTestsRequest(BaseModel):
    """仅运行 L1 质量测试"""
    original_sql: str = Field(..., description="待测试的 SQL 查询")
    db_conn_str: str = Field(..., description="数据库连接字符串")
    dict_path: str | None = Field(None, description="数据字典文件路径")


# ── 通用响应 ────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    index_ready: bool = False
    index_count: int = 0
    langsmith_configured: bool = False


class UploadResponse(BaseModel):
    """数据字典上传结果"""
    success: bool
    layers: list[str] = []
    total_rows: int = 0
    collection_count: int = 0
    saved_path: str = ""
    error: str = ""


class IndexStatusResponse(BaseModel):
    ready: bool
    count: int = 0
    collection: str = ""
    error: str = ""


class PreviewResponse(BaseModel):
    columns: list[str]
    rows: list[list]
    total_rows: int = 0
    error: str = ""


class SchemaUploadResponse(BaseModel):
    """数仓建模 schema 上传结果"""
    success: bool
    source_name: str = ""
    tables_detected: int = 0
    columns_detected: int = 0
    saved_path: str = ""
    error: str = ""


# ── 认证 ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class UserInfo(BaseModel):
    """当前用户信息（含权限）"""
    user_id: int
    username: str
    real_name: str
    is_admin: bool
    department_id: int | None = None
    department_path: str = ""
    visible_dept_ids: list[int] = []
    business_line_codes: list[str] = []


class LoginResponse(BaseModel):
    """登录响应"""
    token: str
    user: UserInfo


class AdminUserCreate(BaseModel):
    """创建用户请求"""
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6)
    real_name: str = Field(..., min_length=1)
    department_id: int
    business_line_ids: list[int] = []
    is_admin: bool = False


class AdminUserUpdate(BaseModel):
    """修改用户请求 — 所有字段可选"""
    real_name: str | None = None
    department_id: int | None = None
    business_line_ids: list[int] | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
    new_password: str | None = Field(None, min_length=6)


class AdminDepartmentCreate(BaseModel):
    """创建部门请求"""
    name: str = Field(..., min_length=1)
    parent_id: int | None = None


class AdminBusinessLineCreate(BaseModel):
    """创建业务条线请求"""
    name: str = Field(..., min_length=1)
    code: str = Field(..., min_length=2, max_length=30)
    description: str = ""


class AdminTableLineMapping(BaseModel):
    """表-条线映射请求"""
    table_name: str
    business_line_id: int
