"""
DataPilot 黑暗主题 — 黑色为主，勃艮第红为辅

在 app.py 中通过 st.markdown(..., unsafe_allow_html=True) 注入。

Palette:
    背景最深:  #0B0E14    主页面背景 (近黑，微蓝底)
    表面:      #141820    卡片 / 输入框 / 容器
    侧边栏:    #080B10    略深于主背景，层次区分
    边框:      #2D333B    分隔线 / 边框
    主文字:    #E0E3E8    高可读性
    次要文字:  #9099A4    标签 / 说明

    主题红:    #B34141    主按钮 / 高亮 / 选中态
    红悬浮:    #C96060    hover / focus
    红暗:      #8B3030    深层红
    红发光:    rgba(179, 65, 65, 0.12)    阴影 / 微光
"""

DARK_THEME_CSS = """<style>
/* ================================================================
   DataPilot 黑暗主题 — Black + Burgundy
   ================================================================ */

/* ── 1. 全局 ─────────────────────────────────────────────── */

.stApp {
    background-color: #0B0E14;
}

.stMain {
    background-color: #0B0E14;
}

.block-container {
    background-color: #0B0E14;
}

body {
    color: #E0E3E8;
    background-color: #0B0E14;
}

/* 滚动条 */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}
::-webkit-scrollbar-track {
    background: #0B0E14;
}
::-webkit-scrollbar-thumb {
    background: #3A2020;
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
    background: #B34141;
}

/* 选中文字 */
::selection {
    background: rgba(179, 65, 65, 0.30);
    color: #E0E3E8;
}

/* ── 2. 侧边栏 ──────────────────────────────────────────── */

[data-testid="stSidebar"] {
    background-color: #080B10;
    border-right: 1px solid #2D333B;
}

[data-testid="stSidebar"] .block-container {
    background-color: #080B10;
}

[data-testid="stSidebar"] * {
    color: #E0E3E8;
}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #E0E3E8 !important;
}

[data-testid="stSidebar"] .st-emotion-cache-6qob1r,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] .stCaptionContainer,
[data-testid="stSidebar"] small,
[data-testid="stSidebar"] caption {
    color: #9099A4 !important;
}

[data-testid="stSidebar"] hr {
    border-color: #2D333B;
}

/* 侧边栏 radio 按钮 */
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    color: #E0E3E8;
}

[data-testid="stSidebar"] div[data-testid="stNotification"] {
    background-color: transparent;
}

/* ── 3. 按钮 ─────────────────────────────────────────────── */

/* 主按钮 — 酒红 */
.stButton > button[kind="primary"],
div[data-testid="stButton"] button[kind="primary"],
button[kind="primary"] {
    background-color: #B34141 !important;
    border-color: #B34141 !important;
    color: #FFFFFF !important;
    border-radius: 6px;
    font-weight: 500;
    transition: background-color 0.2s ease, box-shadow 0.2s ease;
}

.stButton > button[kind="primary"]:hover,
button[kind="primary"]:hover {
    background-color: #C96060 !important;
    border-color: #C96060 !important;
    color: #FFFFFF !important;
    box-shadow: 0 0 0 2px rgba(179, 65, 65, 0.25);
}

.stButton > button[kind="primary"]:active,
button[kind="primary"]:active {
    background-color: #8B3030 !important;
    border-color: #8B3030 !important;
}

/* 次按钮 */
.stButton > button[kind="secondary"],
button[kind="secondary"] {
    background-color: #141820 !important;
    border-color: #3A4444 !important;
    color: #E0E3E8 !important;
    border-radius: 6px;
}

.stButton > button[kind="secondary"]:hover,
button[kind="secondary"]:hover {
    background-color: #1C2333 !important;
    border-color: #B34141 !important;
    color: #C96060 !important;
}

/* 普通按钮（无 kind） */
.stButton > button:not([kind]),
div[data-testid="stButton"] > button:not([kind]) {
    background-color: #141820;
    border-color: #2D333B;
    color: #E0E3E8;
    border-radius: 6px;
}

.stButton > button:not([kind]):hover,
div[data-testid="stButton"] > button:not([kind]):hover {
    border-color: #B34141;
    color: #C96060;
}

/* 禁用按钮 */
.stButton > button:disabled,
button:disabled,
button[kind="primary"]:disabled {
    background-color: #1E2430 !important;
    border-color: #2D333B !important;
    color: #505A66 !important;
    opacity: 0.6;
}

/* ── 4. 文字输入 ────────────────────────────────────────── */

.stTextArea textarea,
textarea[aria-label] {
    background-color: #141820 !important;
    color: #E0E3E8 !important;
    border: 1px solid #2D333B !important;
    border-radius: 6px;
    caret-color: #B34141;
}

.stTextArea textarea:focus,
textarea[aria-label]:focus {
    border-color: #B34141 !important;
    box-shadow: 0 0 0 2px rgba(179, 65, 65, 0.15) !important;
}

.stTextArea textarea::placeholder,
textarea::placeholder {
    color: #505A66 !important;
}

input[type="text"]:not([data-testid="stFileUploader"] input) {
    background-color: #141820 !important;
    color: #E0E3E8 !important;
    border: 1px solid #2D333B !important;
    border-radius: 6px;
    caret-color: #B34141;
}

input[type="text"]:focus {
    border-color: #B34141 !important;
    box-shadow: 0 0 0 2px rgba(179, 65, 65, 0.15) !important;
}

/* 数字输入 */
[data-testid="stNumberInput"] input,
input[type="number"] {
    background-color: #141820 !important;
    color: #E0E3E8 !important;
    border: 1px solid #2D333B !important;
    border-radius: 6px;
    caret-color: #B34141;
}

[data-testid="stNumberInput"] input:focus {
    border-color: #B34141 !important;
    box-shadow: 0 0 0 2px rgba(179, 65, 65, 0.15) !important;
}

/* ── 5. 下拉框 ──────────────────────────────────────────── */

[data-testid="stSelectbox"] select,
select {
    background-color: #141820 !important;
    color: #E0E3E8 !important;
    border: 1px solid #2D333B;
    border-radius: 6px;
}

/* ── 6. 文件上传 ────────────────────────────────────────── */

[data-testid="stFileUploader"] {
    background-color: #141820;
    border: 1px dashed #2D333B;
    border-radius: 8px;
    padding: 1rem;
}

[data-testid="stFileUploader"]:hover {
    border-color: #B34141;
    background-color: #161C24;
}

[data-testid="stFileUploader"] section {
    background-color: transparent;
}

[data-testid="stFileUploader"] span,
[data-testid="stFileUploader"] small {
    color: #9099A4;
}

/* ── 7. 展开面板 ────────────────────────────────────────── */

[data-testid="stExpander"] {
    background-color: #141820;
    border: 1px solid #2D333B;
    border-radius: 8px;
    margin-bottom: 0.5rem;
}

[data-testid="stExpander"] summary {
    color: #E0E3E8;
}

[data-testid="stExpander"] summary:hover {
    color: #C96060;
}

[data-testid="stExpander"] .st-emotion-cache-6qob1r,
[data-testid="stExpanderContent"] {
    background-color: #141820;
}

/* ── 8. 单选按钮 / 复选框 ──────────────────────────────── */

/* 单选按钮 — 标签文字 */
[data-testid="stRadio"] label {
    color: #E0E3E8;
}

/* 单选按钮 — 选中态圆点 */
[data-testid="stRadio"] input[type="radio"]:checked {
    accent-color: #B34141;
}

input[type="radio"]:checked {
    accent-color: #B34141;
}

/* 复选框 */
input[type="checkbox"]:checked {
    accent-color: #B34141;
}

[data-testid="stCheckbox"] label {
    color: #E0E3E8;
}

/* ── 9. 数据表格 ────────────────────────────────────────── */

.stDataFrame,
[data-testid="stDataFrame"],
.dataframe {
    background-color: #141820;
    border: 1px solid #2D333B;
    border-radius: 8px;
}

.stDataFrame table,
[data-testid="stDataFrame"] table {
    background-color: #141820;
}

.stDataFrame thead th,
[data-testid="stDataFrame"] thead th,
.dataframe thead th {
    background-color: #1A2130 !important;
    color: #9099A4 !important;
    border-bottom: 2px solid #2D333B !important;
    font-weight: 600;
}

.stDataFrame tbody td,
[data-testid="stDataFrame"] tbody td,
.dataframe tbody td {
    background-color: #141820;
    color: #E0E3E8;
    border-bottom: 1px solid #1E2430;
}

.stDataFrame tbody tr:hover td,
[data-testid="stDataFrame"] tbody tr:hover td {
    background-color: #1A2130;
}

/* ── 10. 指标卡片 ──────────────────────────────────────── */

[data-testid="stMetricValue"] {
    color: #E0E3E8;
    font-weight: 700;
}

[data-testid="stMetricLabel"] {
    color: #9099A4;
}

/* ── 11. 代码块 ────────────────────────────────────────── */

.stCodeBlock,
[data-testid="stCodeBlock"],
pre code,
code {
    background-color: #0D1117 !important;
    color: #E0E3E8;
    border: 1px solid #2D333B;
    border-radius: 6px;
}

.stCodeBlock code,
pre code {
    background-color: transparent !important;
    border: none;
}

/* 内联代码 */
p code:not(pre code),
span code:not(pre code) {
    background-color: #1E2430;
    color: #C96060;
    border: 1px solid #2D333B;
    border-radius: 4px;
    padding: 2px 6px;
}

/* ── 12. 状态消息 ──────────────────────────────────────── */

/* 成功 */
div[data-testid="stNotification"][kind="success"],
div[data-testid="stAlert"][kind="success"],
.stSuccess {
    background-color: #0D1F15 !important;
    border: 1px solid #1A4A2A !important;
    border-left: 4px solid #2D8A4E !important;
    color: #7BC98F !important;
    border-radius: 6px;
}

/* 错误 */
div[data-testid="stNotification"][kind="error"],
div[data-testid="stAlert"][kind="error"],
.stError {
    background-color: #1F0D0D !important;
    border: 1px solid #4A1A1A !important;
    border-left: 4px solid #B34141 !important;
    color: #D98080 !important;
    border-radius: 6px;
}

/* 警告 */
div[data-testid="stNotification"][kind="warning"],
div[data-testid="stAlert"][kind="warning"],
.stWarning {
    background-color: #1F1A0D !important;
    border: 1px solid #4A3A1A !important;
    border-left: 4px solid #C08030 !important;
    color: #D9B860 !important;
    border-radius: 6px;
}

/* 信息 */
div[data-testid="stNotification"][kind="info"],
div[data-testid="stAlert"][kind="info"],
.stInfo {
    background-color: #0D151F !important;
    border: 1px solid #1A2A4A !important;
    border-left: 4px solid #3050A0 !important;
    color: #80A0D0 !important;
    border-radius: 6px;
}

/* ── 13. 链接 ────────────────────────────────────────────── */

a {
    color: #C96060;
    text-decoration: none;
}

a:hover {
    color: #D98080;
    text-decoration: underline;
}

/* ── 14. 分隔线 ──────────────────────────────────────────── */

hr,
[data-testid="stDivider"] {
    border-color: #2D333B;
}

.stDivider {
    border-color: #2D333B;
}

/* ── 15. 加载动画 ───────────────────────────────────────── */

.stSpinner {
    border-color: #B34141;
}

/* ── 16. 进度条 ─────────────────────────────────────────── */

[data-testid="stProgress"] > div {
    background-color: #B34141;
    border-radius: 4px;
}

[data-testid="stProgress"] {
    background-color: #1E2430;
    border-radius: 4px;
}

/* ── 17. 下载按钮 ───────────────────────────────────────── */

[data-testid="stDownloadButton"] button {
    background-color: #141820 !important;
    border-color: #2D333B !important;
    color: #E0E3E8 !important;
    border-radius: 6px;
}

[data-testid="stDownloadButton"] button:hover {
    border-color: #B34141 !important;
    color: #C96060 !important;
}

/* ── 18. 标题 & 文字 ────────────────────────────────────── */

h1, h2, h3, h4, h5, h6 {
    color: #E0E3E8 !important;
}

p, span, li, td, th, label {
    color: #E0E3E8;
}

small, caption, .stCaption, [data-testid="stCaptionContainer"] {
    color: #9099A4 !important;
}

/* ── 19. 标签 / tooltip ─────────────────────────────────── */

[data-testid="stTooltipContent"] {
    background-color: #1C2333;
    color: #E0E3E8;
    border: 1px solid #2D333B;
    border-radius: 6px;
}

/* ── 20. Label / 帮助文字 ────────────────────────────────── */

[data-testid="stWidgetLabel"] p,
.stMarkdown small {
    color: #9099A4;
}

</style>"""
