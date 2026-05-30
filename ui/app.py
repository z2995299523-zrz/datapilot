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
    st.markdown("上传数据字典文件（CSV 或 Excel），构建 ChromaDB 向量索引。")

    # File upload
    uploaded_file = st.file_uploader(
        "选择数据字典文件",
        type=["csv", "xlsx"],
        help="支持 .csv 和 .xlsx 格式，需包含列: layer, table_name, column_name, column_type, column_comment",
    )

    if uploaded_file:
        # Save to temp file
        import tempfile
        suffix = ".xlsx" if uploaded_file.name.endswith(".xlsx") else ".csv"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        # Preview table
        st.subheader("📋 文件预览")
        import pandas as pd
        if tmp_path.endswith(".xlsx"):
            df = pd.read_excel(tmp_path)
        else:
            df = pd.read_csv(tmp_path)
        st.dataframe(df.head(20), use_container_width=True)
        st.caption(f"共 {len(df)} 行")

        # Check required columns
        required = ["layer", "table_name", "column_name"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            st.error(f"❌ 缺少必要列: {', '.join(missing)}。请检查文件格式。")
        else:
            detected_layers = df['layer'].dropna().unique()
            st.success(f"✅ 列结构正确。检测到 {len(detected_layers)} 个数据层: {', '.join(detected_layers)}")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔨 构建索引", type="primary", use_container_width=True):
                    with st.spinner("正在构建 ChromaDB 索引..."):
                        try:
                            from dictionary.loader import load_dictionary
                            from dictionary.indexer import build_index
                            data_dict = load_dictionary(tmp_path)
                            collection = build_index(data_dict, reset=True)
                            st.session_state["index_ready"] = True
                            st.session_state["index_count"] = collection.count()
                            st.success(f"✅ 索引构建完成！共 {collection.count()} 条记录")
                        except Exception as e:
                            st.error(f"❌ 索引构建失败: {e}")
            with col2:
                if st.button("🗑 重建索引", use_container_width=True):
                    with st.spinner("正在重建索引..."):
                        try:
                            from dictionary.loader import load_dictionary
                            from dictionary.indexer import build_index
                            data_dict = load_dictionary(tmp_path)
                            collection = build_index(data_dict, reset=True)
                            st.session_state["index_ready"] = True
                            st.session_state["index_count"] = collection.count()
                            st.success(f"✅ 索引重建完成！共 {collection.count()} 条记录")
                        except Exception as e:
                            st.error(f"❌ 重建失败: {e}")

        # Cleanup temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    # Index status section
    st.divider()
    st.subheader("📊 索引状态")
    from config import CHROMA_DIR, CHROMA_COLLECTION
    try:
        from chromadb import PersistentClient
        from chromadb.config import Settings as ChromaSettings
        client = PersistentClient(
            path=str(CHROMA_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collections = client.list_collections()
        existing = [c for c in collections if c.name == CHROMA_COLLECTION]
        if existing:
            count = client.get_collection(CHROMA_COLLECTION).count()
            st.success(f"✅ 索引已就绪 — 集合 `{CHROMA_COLLECTION}` 包含 {count} 条记录")
            st.session_state["index_ready"] = True
        else:
            st.warning("⚠ 尚未构建索引。请上传数据字典文件并点击「构建索引」。")
            st.session_state["index_ready"] = False
    except Exception as e:
        st.error(f"❌ 无法连接 ChromaDB: {e}")
        st.session_state["index_ready"] = False
elif page == "🔍 需求分析":
    st.title("🔍 需求分析")
    st.info("输入业务需求文档，自动提取概念、检索匹配、生成分析伪代码。")
elif page == "🔧 修复闭环":
    st.title("🔧 修复闭环")
    st.info("输入 SQL 查询，运行三层测试并进行诊断与自动修复。")
