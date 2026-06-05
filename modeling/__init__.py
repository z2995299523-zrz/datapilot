"""
DataPilot 数仓建模引擎

从业务数据库 schema 自动搭建分层数仓模型:
  1. 表角色分类 (fact/dim/bridge/agg)
  2. 分层分配 (ODS → DWS → ADS → DM)
  3. FK-PK 关系检测
  4. 码值列识别
  5. 口径一致性校验
  6. 模式分类 (star/snowflake/3NF)
  7. 模型演进 (新增表合并/创建)
"""
