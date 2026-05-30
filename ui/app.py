"""
DataPilot Streamlit WebUI — 数据需求分析全链路可视化

用法: streamlit run ui/app.py
"""
import streamlit as st
import os

st.set_page_config(
    page_title="DataPilot — 需求分析引擎",
    page_icon="📊",
    layout="wide",
)

# --- Sidebar ---
st.sidebar.title("📊 DataPilot")
st.sidebar.caption("需求→SQL→测试→修复 全链路引擎")

page = st.sidebar.radio(
    "导航",
    ["📚 数据字典管理", "🔍 需求分析", "🔧 修复闭环"],
)

# --- LangSmith status indicator ---
langsmith_configured = bool(
    os.getenv("LANGCHAIN_API_KEY")
    and os.getenv("LANGCHAIN_API_KEY") != "your-langsmith-api-key"
)
if langsmith_configured:
    st.sidebar.success("🟢 LangSmith 已连接")
else:
    st.sidebar.warning("🔴 LangSmith 未配置")

st.sidebar.divider()
st.sidebar.caption("Phase 4 | 210 tests")

# --- Page routing ---
if page == "📚 数据字典管理":
    st.title("📚 数据字典管理")
    st.info("上传数据字典并构建向量索引，供需求分析使用。")
elif page == "🔍 需求分析":
    st.title("🔍 需求分析")
    st.info("输入业务需求文档，自动提取概念、检索匹配、生成分析伪代码。")
elif page == "🔧 修复闭环":
    st.title("🔧 修复闭环")
    st.info("输入 SQL 查询，运行三层测试并进行诊断与自动修复。")
