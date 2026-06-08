"""auth ORM models — Department, BusinessLine, User, UserBusinessLine, TableBusinessLine, TableDeptColumn"""
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Table,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

# Association tables for many-to-many
user_business_lines = Table(
    "user_business_lines", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("business_line_id", Integer, ForeignKey("business_lines.id"), primary_key=True),
)

table_business_lines = Table(
    "table_business_lines", Base.metadata,
    Column("table_name", String, primary_key=True),
    Column("business_line_id", Integer, ForeignKey("business_lines.id"), primary_key=True),
)


class Department(Base):
    """部门 — 树形结构，物化路径 /总行/北京分行/海淀支行"""
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    path = Column(String, nullable=False, unique=True)      # Materialized path: "/总行/北京分行/海淀支行"
    level = Column(Integer, nullable=False)                  # Depth: root=0
    is_active = Column(Integer, default=1)
    parent = relationship("Department", remote_side=[id], backref="children")


class BusinessLine(Base):
    """业务线 — code 唯一标识，如 retail / aml / corporate / ops"""
    __tablename__ = "business_lines"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=False, unique=True)       # "retail", "aml"
    description = Column(String, default="")
    is_active = Column(Integer, default=1)


class User(Base):
    """用户 — 所属部门 + 业务线权限（多对多）"""
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)           # bcrypt hash
    real_name = Column(String, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    is_admin = Column(Integer, default=0)
    is_active = Column(Integer, default=1)
    created_at = Column(String, default="")
    department = relationship("Department")
    business_lines = relationship("BusinessLine", secondary=user_business_lines)


class TableDeptColumn(Base):
    """表机构字段映射 — 记录每张表的哪个字段是机构代码"""
    __tablename__ = "table_dept_columns"
    table_name = Column(String, primary_key=True)
    dept_column = Column(String, nullable=False)             # Which column in this table stores dept code
