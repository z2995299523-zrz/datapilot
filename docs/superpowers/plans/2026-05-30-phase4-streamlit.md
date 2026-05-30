# Phase 4: Streamlit + LangSmith Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 3-page Streamlit WebUI that wraps the existing CLI pipeline, plus LangSmith trace configuration.

**Architecture:** Single file `ui/app.py` with 3 pages (dictionary management, requirement analysis, reconciliation). All logic delegates to existing modules — no duplication. LangSmith is purely env-config.

**Tech Stack:** Streamlit (new dep), existing datapilot modules (extractor, retrieval, generator, testing, reconciliation)

---

### Task 1: Add streamlit dependency and LangSmith config

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`

- [ ] **Step 1: Add streamlit to requirements.txt**

Add after existing content:
```
streamlit>=1.28.0
```

- [ ] **Step 2: Add LangSmith config to .env.example**

Append to existing file:
```
# LangSmith tracing (Phase 4 — optional)
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=your-langsmith-api-key
LANGCHAIN_PROJECT=datapilot
```

- [ ] **Step 3: Verify dependencies install**

Run: `pip install streamlit>=1.28.0`
Expected: streamlit installed without conflicts

- [ ] **Step 4: Commit**

```bash
git add requirements.txt .env.example
git commit -m "chore: add streamlit dependency and LangSmith config template"
```

---

### Task 2: Create Streamlit UI — shared utilities and page structure

**Files:**
- Create: `ui/__init__.py`
- Create: `ui/app.py` (skeleton)

- [ ] **Step 1: Create ui directory and init file**

```python
# ui/__init__.py — placeholder
```

- [ ] **Step 2: Create app.py skeleton with 3-page sidebar navigation**

```python
"""
DataPilot Streamlit WebUI — 数据需求分析全链路可视化

用法: streamlit run ui/app.py
"""
import streamlit as st

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
import os
langsmith_configured = bool(os.getenv("LANGCHAIN_API_KEY") and os.getenv("LANGCHAIN_API_KEY") != "your-langsmith-api-key")
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
```

- [ ] **Step 3: Verify app launches (smoke test)**

Run: `streamlit run ui/app.py` (then Ctrl+C to stop)
Expected: App starts, sidebar with 3 pages visible, no errors

- [ ] **Step 4: Commit**

```bash
git add ui/__init__.py ui/app.py
git commit -m "feat: add Streamlit UI skeleton with 3-page navigation"
```

---

### Task 3: Page 1 — 数据字典管理

**Files:**
- Modify: `ui/app.py` (replace placeholder in page 1 section)

- [ ] **Step 1: Implement dictionary management page**

Replace the Page 1 placeholder with:

```python
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
        # Save to temp
        import tempfile
        suffix = ".xlsx" if uploaded_file.name.endswith(".xlsx") else ".csv"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        # Preview
        st.subheader("📋 文件预览")
        import pandas as pd
        if tmp_path.endswith(".xlsx"):
            df = pd.read_excel(tmp_path)
        else:
            df = pd.read_csv(tmp_path)
        st.dataframe(df.head(20), use_container_width=True)
        st.caption(f"共 {len(df)} 行")

        # Column check
        required = ["layer", "table_name", "column_name"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            st.error(f"❌ 缺少必要列: {', '.join(missing)}。请检查文件格式。")
        else:
            st.success(f"✅ 列结构正确。检测到 {df['layer'].nunique()} 个数据层: {', '.join(df['layer'].dropna().unique())}")

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

        # Cleanup
        import os as _os
        try:
            _os.unlink(tmp_path)
        except Exception:
            pass

    # Index status
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
            st.warning(f"⚠ 尚未构建索引。请上传数据字典文件并点击「构建索引」。")
            st.session_state["index_ready"] = False
    except Exception as e:
        st.error(f"❌ 无法连接 ChromaDB: {e}")
        st.session_state["index_ready"] = False
```

- [ ] **Step 2: Verify page works**

Run: `streamlit run ui/app.py`
Expected: Upload CSV → preview table → build index → status shows ready

- [ ] **Step 3: Commit**

```bash
git add ui/app.py
git commit -m "feat: add dictionary management page"
```

---

### Task 4: Page 2 — 需求分析

**Files:**
- Modify: `ui/app.py` (replace placeholder in page 2 section)

- [ ] **Step 1: Implement requirement analysis page**

Replace the Page 2 placeholder with:

```python
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
        from config import CHROMA_COLLECTION
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
                            codes = ", ".join(f"{cv.value}={cv.meaning}" for cv in col.code_values)
                            codes_info += f"  - {col.name}: {codes}\n"
                    st.success(f"**[{m.layer.value}层] {m.table_name}** (score={m.score:.2f})")
                    st.caption(m.table_comment)
                    if codes_info:
                        st.code(codes_info.strip(), language=None)
                else:
                    st.warning(f"**[未匹配] {m.concept}** — {m.message}")

            if result.unmatched_concepts:
                st.error(f"待确认: {', '.join(result.unmatched_concepts)}")

        # Step 3: Pseudocode
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

        # Step 4: SQL (optional)
        if generate_sql:
            with st.spinner("生成 SQL 脚本..."):
                from dictionary.loader import load_dictionary
                from generator.script import generate_sql as gen_sql
                # We need the data dict for JOIN inference — use the uploaded file if provided
                # Fall back to demo data
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
```

- [ ] **Step 2: Verify page works**

Run: `streamlit run ui/app.py`
Prerequisite: index must be built (use Page 1 first)
Expected: Enter requirement → click analyze → 3 steps expand with results → SQL shown

- [ ] **Step 3: Commit**

```bash
git add ui/app.py
git commit -m "feat: add requirement analysis page"
```

---

### Task 5: Page 3 — 修复闭环

**Files:**
- Modify: `ui/app.py` (replace placeholder in page 3 section)

- [ ] **Step 1: Implement reconciliation page**

Replace the Page 3 placeholder with:

```python
elif page == "🔧 修复闭环":
    st.title("🔧 修复闭环")
    st.markdown("输入 SQL 查询，运行 L1 数据质量 + L2 逻辑比对 + L3 诊断，自动修复并重测。")

    # Input
    original_sql = st.text_area(
        "输入需要测试的 SQL",
        height=150,
        placeholder="SELECT cust_id, channel_type, COUNT(*) as cnt\nFROM dm_customer_active\nGROUP BY cust_id, channel_type",
    )
    requirement_text = st.text_area(
        "原始需求文档（可选，用于提供业务上下文）",
        height=100,
        placeholder="在此粘贴需求文档...",
    )

    col1, col2 = st.columns(2)
    with col1:
        max_loops = st.number_input("最大重试次数", min_value=1, max_value=10, value=3)
    with col2:
        db_conn_str = st.text_input(
            "数据库连接字符串（可选）",
            placeholder="sqlite:///test.db 或 留空跳过实际执行",
        )

    if st.button("🔍 运行测试", type="primary", disabled=not original_sql.strip()):
        import json
        from models import ColumnInfo

        # Build column info from demo dict for demo purposes
        from pathlib import Path
        from dictionary.loader import load_dictionary
        demo_path = Path(__file__).parent.parent / "demo" / "data_dict.csv"
        data_dict = load_dictionary(str(demo_path))

        # Extract columns from the first DM table as demo columns
        dm_tables = [t for t in data_dict.tables if t.layer.value == "DM"]
        if dm_tables:
            column_infos = dm_tables[0].columns
        else:
            st.error("未找到 DM 层数据，请先构建索引。")
            st.stop()

        pk_columns = [c.name for c in column_infos if c.is_primary_key]

        st.divider()
        st.subheader("📊 测试执行")

        # Database connection
        conn = None
        if db_conn_str:
            try:
                from sqlalchemy import create_engine, text
                engine = create_engine(db_conn_str)
                conn = engine.connect()
                st.success(f"✅ 已连接数据库")
            except Exception as e:
                st.error(f"❌ 数据库连接失败: {e}。将跳过实际执行，仅展示流程。")

        # Run reconciliation
        progress_placeholder = st.empty()

        if conn is not None:
            # Real execution
            try:
                from reconciliation.graph import run_reconciliation
                with st.spinner("正在执行测试与修复闭环..."):
                    final_state = run_reconciliation(
                        conn=conn,
                        original_sql=original_sql,
                        column_infos=column_infos,
                        requirement_text=requirement_text,
                        pk_columns=pk_columns,
                        max_loops=max_loops,
                    )

                # Display results by round
                fix_history = json.loads(final_state.get("fix_history_json", "[]"))
                for i, fix_entry in enumerate(fix_history):
                    round_num = i + 1
                    with st.expander(f"🔄 第 {round_num} 轮", expanded=(i == len(fix_history) - 1)):
                        st.json(fix_entry)

                if final_state.get("status") == "passed":
                    st.success(f"🎉 全部通过！共执行 {len(fix_history)} 轮修复")
                else:
                    st.warning(f"⚠ 测试未完全通过。状态: {final_state.get('status')}")
                    if final_state.get("error_message"):
                        st.error(final_state["error_message"])

            except Exception as e:
                st.error(f"❌ 执行失败: {e}")
            finally:
                conn.close()
        else:
            # Dry-run: show what would happen
            st.info("ℹ 未连接数据库，展示诊断流程。请连接数据库以执行实际测试。")

            with st.expander("🔍 模拟运行 — L1 基础质量检查", expanded=True):
                st.markdown("""
                将执行的检查项（基于数据字典元数据）:
                - ✅ 主键唯一性: `GROUP BY {pk} HAVING COUNT(*) > 1`
                - ✅ 空值率: 对每个字段检查 NULL 比例
                - ✅ 字段超长: 对比 varchar(N) 与 MAX(LENGTH(col))
                - ✅ 码值合法性: 对比列值与数据字典中定义的合法码值
                """)
                st.caption("实际执行时需要数据库连接。当前为流程预览。")

            with st.expander("🔧 模拟运行 — L3 诊断与修复", expanded=False):
                st.markdown("""
                如检测到失败，将触发诊断引擎:
                1. L1: 数据源检查
                2. L2: 码值映射检查
                3. L3: JOIN 逻辑检查
                4. L4: 业务口径检查
                5. L5: 概念遗漏检查

                可自动修复项: 码值替换、CAST 转换、补充 WHERE 条件
                不可自动修复: 需求口径不匹配 → 生成人工确认报告
                """)

            with st.expander("📝 结果预览", expanded=False):
                st.json({
                    "status": "dry_run",
                    "message": "此模式仅展示流程。连接数据库后可执行实际测试。",
                    "loop_count": 0,
                    "max_loops": max_loops,
                    "column_count": len(column_infos),
                    "pk_columns": pk_columns,
                })

    # Usage guide
    st.divider()
    with st.expander("💡 使用说明"):
        st.markdown("""
        **连接数据库后可执行完整的测试→诊断→修复闭环:**
        1. 输入需要测试的 SQL 查询
        2. 填写数据库连接字符串（支持 SQLite/MySQL/PostgreSQL）
        3. 点击运行测试
        4. 系统自动执行 L1/L2/L3 三层测试
        5. 失败项自动诊断并尝试修复
        6. 修复后重测，最多重试指定次数

        **不连接数据库时**展示诊断流程和可检测的问题类型。
        """)
```

- [ ] **Step 2: Verify page works**

Run: `streamlit run ui/app.py`
Expected: Enter SQL → click run → dry-run shows diagnostic flow. With DB connection, real execution.

- [ ] **Step 3: Commit**

```bash
git add ui/app.py
git commit -m "feat: add reconciliation page"
```

---

### Task 6: Update CLAUDE.md with Streamlit commands

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add Streamlit commands to CLAUDE.md**

In the "常用命令" section, after the CLI commands, add:

```bash
# 启动 Streamlit WebUI
streamlit run ui/app.py
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add Streamlit launch command to CLAUDE.md"
```

---

### Task 7: End-to-end smoke test

**Files:**
- None (manual test)

- [ ] **Step 1: Full flow test**

```bash
# 1. Start the app
streamlit run ui/app.py

# 2. Manual verification checklist:
#  [ ] Page 1: Upload demo/data_dict.csv → preview shows data → build index
#  [ ] Page 2: Paste demo/req_sample.txt content → analyze → 3 steps expand → SQL shown
#  [ ] Page 3: Enter a simple SQL → dry-run shows diagnostic flow
#  [ ] LangSmith indicator in sidebar shows status
```

- [ ] **Step 2: Verify no regressions**

```bash
pytest tests/ -v
```

Expected: all 210 tests still pass

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "test: verify Phase 4 Streamlit UI end-to-end flow"
```
