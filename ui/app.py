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
    st.markdown("输入业务需求文档，自动完成概念提取 → 分层检索 → 伪代码生成 → SQL 生成。")

    # Prerequisite check
    index_ready = st.session_state.get("index_ready", False)
    if not index_ready:
        st.warning("⚠ 请先在「数据字典管理」页面构建索引。")
        st.stop()

    # Input
    col1, col2 = st.columns([3, 1])
    with col1:
        requirement_text = st.text_area(
            "业务需求文档",
            height=200,
            placeholder="例如：统计近6个月各渠道的活跃客户数及交易金额，按渠道类型分组展示...",
            key="req_text",
        )
    with col2:
        uploaded_req = st.file_uploader("或上传 .txt 文件", type=["txt"], key="req_upload")
        if uploaded_req:
            requirement_text = uploaded_req.getvalue().decode("utf-8")
            st.text_area("已加载文件", requirement_text, height=200, disabled=True)

    generate_sql = st.checkbox("生成 SQL 脚本", value=True)

    if st.button("🚀 开始分析", type="primary", disabled=not requirement_text.strip()):
        from config import CHROMA_COLLECTION, CHROMA_DIR
        from chromadb import PersistentClient
        from chromadb.config import Settings as ChromaSettings

        client = PersistentClient(
            path=str(CHROMA_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = client.get_collection(CHROMA_COLLECTION)

        # Step 1: Concept extraction
        with st.spinner("步骤 1/3: 提取业务概念..."):
            from extractor.concept import extract_concepts
            extraction = extract_concepts(requirement_text)

        with st.expander(f"📊 步骤 1/3: 提取到 {len(extraction.concepts)} 个业务概念", expanded=True):
            for c in extraction.concepts:
                candidates = f" ({', '.join(c.candidates)})" if c.candidates else ""
                st.markdown(f"- **[{c.type.value}] {c.concept}**{candidates}")
                if c.qualifier:
                    st.caption(f"  限定: `{c.qualifier}`")

        # Step 2: Retrieval
        with st.spinner("步骤 2/3: 分层检索..."):
            from retrieval.engine import search
            result = search(extraction.concepts, collection)

        matched_count = sum(1 for m in result.matches if m.matched)
        with st.expander(f"🔍 步骤 2/3: 匹配 {matched_count}/{len(result.matches)}，未匹配 {len(result.unmatched_concepts)}", expanded=True):
            for m in result.matches:
                if m.matched:
                    codes_info = ""
                    for col in m.columns:
                        if col.code_values:
                            codes = ", ".join(f"{cv.value}={cv.meaning}" for cv in col.code_values[:6])
                            codes_info += f"  - {col.name}: {codes}\n"
                    st.success(f"**[{m.layer.value}层] {m.table_name}** (score={m.score:.2f})")
                    st.caption(m.table_comment)
                    if codes_info:
                        st.code(codes_info.strip(), language=None)
                else:
                    st.warning(f"**[未匹配] {m.concept}** — {m.message}")

            if result.unmatched_concepts:
                st.error(f"待确认: {', '.join(result.unmatched_concepts)}")

        # Step 3: Pseudocode generation
        with st.spinner("步骤 3/3: 生成分析伪代码..."):
            from generator.pseudocode import generate
            pseudocode = generate(requirement_text, result, extraction.concepts)

        with st.expander(f"📝 步骤 3/3: {pseudocode.title}", expanded=True):
            for step in pseudocode.steps:
                st.markdown(f"**步骤 {step.step_number}: {step.description}**")
                details = []
                if step.source_table:
                    details.append(f"- 源表: `{step.source_table}`")
                for cond in step.conditions:
                    details.append(f"- 条件: `{cond}`")
                for join in step.joins:
                    details.append(f"- 关联: `{join}`")
                for agg in step.aggregations:
                    details.append(f"- 聚合: `{agg}`")
                if step.output:
                    details.append(f"- 输出: {step.output}")
                st.markdown("\n".join(details))

            if pseudocode.todo_items:
                st.warning("⚠ 待确认:\n" + "\n".join(f"- {t}" for t in pseudocode.todo_items))
            if pseudocode.notes:
                st.info("📝 备注:\n" + "\n".join(f"- {n}" for n in pseudocode.notes))

        # Step 4: SQL generation (optional)
        if generate_sql:
            with st.spinner("生成 SQL 脚本..."):
                from dictionary.loader import load_dictionary
                from generator.script import generate_sql as gen_sql
                from pathlib import Path
                demo_path = Path(__file__).parent.parent / "demo" / "data_dict.csv"
                data_dict = load_dictionary(str(demo_path))
                tables = {t.table_name: t for t in data_dict.tables}
                sql = gen_sql(pseudocode, tables)

            with st.expander("💾 生成 SQL", expanded=True):
                st.code(sql, language="sql")
                st.download_button(
                    "📥 下载 SQL",
                    sql,
                    file_name="analysis.sql",
                    mime="text/plain",
                )
elif page == "🔧 修复闭环":
    st.title("🔧 修复闭环")
    st.info("输入 SQL 查询，运行三层测试并进行诊断与自动修复。")
