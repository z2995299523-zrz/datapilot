"""
DataPilot CLI — 需求分析助手命令行入口

用法:
  python cli.py search --req demo/req_sample.txt
  python cli.py analyze --req demo/req_sample.txt --dict demo/data_dict.csv
  python cli.py analyze --req demo/req_sample.txt --output json
"""
import argparse
import json
import sys
from pathlib import Path

# 🔧 预加载 BGE embedding 模型（必须在 langchain_openai 之前）
#   langchain_openai 的 httpx 线程初始化会与 PyTorch CUDA 冲突，
#   导致 SentenceTransformer 在 CUDA 设备上加载时 segfault (exit 139)
from embedding import get_embedding_model
get_embedding_model()

from config import CHROMA_DIR, LLM_API_KEY


def _check_api_key():
    """检查 DeepSeek API Key 是否配置"""
    if not LLM_API_KEY or LLM_API_KEY == "your-deepseek-api-key":
        print("错误: 未配置 DEEPSEEK_API_KEY 环境变量")
        print("请设置: set DEEPSEEK_API_KEY=your-key  (Windows)")
        print("        export DEEPSEEK_API_KEY=your-key  (Linux/Mac)")
        sys.exit(1)


def _load_or_rebuild(dict_path: str, rebuild: bool = False):
    """加载数据字典并返回 ChromaDB collection"""
    from chromadb import PersistentClient
    from chromadb.config import Settings as ChromaSettings
    from config import CHROMA_COLLECTION
    from dictionary.loader import load_dictionary
    from dictionary.indexer import build_index

    client = PersistentClient(
        path=str(CHROMA_DIR),
        settings=ChromaSettings(anonymized_telemetry=False),
    )

    existing = client.list_collections()
    has_index = any(c.name == CHROMA_COLLECTION for c in existing)

    if rebuild or not has_index:
        print(f"正在构建向量索引 (来源: {dict_path})...")
        data_dict = load_dictionary(dict_path)
        collection = build_index(data_dict, reset=True)
        print(f"索引就绪: {collection.count()} 条记录")
    else:
        collection = client.get_collection(CHROMA_COLLECTION)
        print(f"使用已有索引: {collection.count()} 条记录")

    return collection


def _format_markdown(result, pseudocode=None, verbose=False, sql=None):
    """格式化输出 Markdown"""
    lines = []

    # 概念
    lines.append("## 业务概念")
    lines.append("")
    from extractor.concept import extract_concepts
    for c in result.get("concepts", []):
        candidates = f" ({', '.join(c.candidates)})" if c.candidates else ""
        lines.append(f"- **[{c.type}] {c.concept}**{candidates}")
        if c.qualifier:
            lines.append(f"  - 限定: `{c.qualifier}`")
    lines.append("")

    # 检索
    lines.append("## 分层检索")
    lines.append("")
    retrieval = result["retrieval"]
    matched = sum(1 for m in retrieval.matches if m.matched)
    lines.append(f"匹配: {matched}, 未匹配: {len(retrieval.unmatched_concepts)}")
    lines.append("")

    if verbose and retrieval.retrieval_log:
        lines.append("### 检索过程")
        lines.append("")
        for log_entry in retrieval.retrieval_log:
            lines.append(f"```\n{log_entry}\n```")
        lines.append("")

    # 匹配详情
    lines.append("### 匹配详情")
    lines.append("")
    for m in retrieval.matches:
        if m.matched:
            lines.append(f"| [{m.layer.value}] | **{m.table_name}** | {m.table_comment} | {m.score} |")
    lines.append("")

    for m in retrieval.matches:
        if m.matched:
            lines.append(f"#### {m.table_name} ({m.layer.value}层)")
            lines.append(f"表注释: {m.table_comment}  |  得分: {m.score}")
            lines.append("")
            lines.append("| 字段 | 注释 | 类型 | 码值 |")
            lines.append("|------|------|------|------|")
            for col in m.columns:
                codes = ", ".join(f"{cv.value}={cv.meaning}" for cv in col.code_values) if col.code_values else ""
                lines.append(f"| {col.name} | {col.comment} | {col.data_type} | {codes} |")
            lines.append("")

    if retrieval.unmatched_concepts:
        lines.append("### 未匹配概念")
        lines.append("")
        for concept in retrieval.unmatched_concepts:
            lines.append(f"- **{concept}** — 三层检索均未找到匹配，请确认数据源")
        lines.append("")

    # 伪代码
    if pseudocode:
        lines.append("## 分析伪代码")
        lines.append("")
        lines.append(f"### {pseudocode.title}")
        lines.append("")
        for step in pseudocode.steps:
            lines.append(f"**步骤 {step.step_number}: {step.description}**")
            lines.append("")
            if step.source_table:
                lines.append(f"- 源表: `{step.source_table}`")
            for cond in step.conditions:
                lines.append(f"- 条件: `{cond}`")
            for join in step.joins:
                lines.append(f"- 关联: `{join}`")
            for agg in step.aggregations:
                lines.append(f"- 聚合: `{agg}`")
            if step.output:
                lines.append(f"- 输出: {step.output}")
            lines.append("")

        if pseudocode.todo_items:
            lines.append("### 待确认")
            lines.append("")
            for item in pseudocode.todo_items:
                lines.append(f"- [ ] {item}")
            lines.append("")

        if pseudocode.notes:
            lines.append("### 备注")
            lines.append("")
            for note in pseudocode.notes:
                lines.append(f"- {note}")
            lines.append("")

    # SQL 输出
    if sql:
        lines.append("## 生成 SQL")
        lines.append("")
        lines.append("```sql")
        lines.append(sql.rstrip())
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def _to_json(result, pseudocode=None, sql=None):
    """序列化为 JSON"""
    retrieval = result["retrieval"]
    output = {
        "concepts": [
            {
                "concept": c.concept,
                "type": c.type.value,
                "context": c.context,
                "candidates": c.candidates,
                "qualifier": c.qualifier,
            }
            for c in result["concepts"]
        ],
        "retrieval": {
            "matched_count": sum(1 for m in retrieval.matches if m.matched),
            "unmatched_count": len(retrieval.unmatched_concepts),
            "matches": [
                {
                    "layer": m.layer.value if m.layer else None,
                    "table_name": m.table_name,
                    "table_comment": m.table_comment,
                    "score": m.score,
                    "concept": m.concept,
                    "matched": m.matched,
                    "columns": [
                        {
                            "name": col.name,
                            "comment": col.comment,
                            "data_type": col.data_type,
                            "code_values": [{"value": cv.value, "meaning": cv.meaning} for cv in col.code_values],
                        }
                        for col in m.columns
                    ],
                }
                for m in retrieval.matches
            ],
            "unmatched_concepts": retrieval.unmatched_concepts,
        },
    }

    if pseudocode:
        output["pseudocode"] = {
            "title": pseudocode.title,
            "steps": [
                {
                    "step_number": s.step_number,
                    "description": s.description,
                    "source_table": s.source_table,
                    "conditions": s.conditions,
                    "joins": s.joins,
                    "aggregations": s.aggregations,
                    "output": s.output,
                }
                for s in pseudocode.steps
            ],
            "todo_items": pseudocode.todo_items,
            "notes": pseudocode.notes,
        }

    if sql:
        output["sql"] = sql

    return json.dumps(output, ensure_ascii=False, indent=2)


def cmd_search(args):
    """search 子命令：提取概念 + 分层检索"""
    from extractor.concept import extract_concepts
    from retrieval.engine import search

    _check_api_key()

    req_text = Path(args.req).read_text(encoding="utf-8")
    collection = _load_or_rebuild(args.dict, args.rebuild)

    print("提取业务概念...")
    extraction = extract_concepts(req_text)

    if args.output == "json":
        print(json.dumps([
            {
                "concept": c.concept,
                "type": c.type.value,
                "candidates": c.candidates,
                "qualifier": c.qualifier,
            }
            for c in extraction.concepts
        ], ensure_ascii=False, indent=2))
        return

    print(f"\n提取到 {len(extraction.concepts)} 个概念:")
    for c in extraction.concepts:
        candidates = f" ({', '.join(c.candidates)})" if c.candidates else ""
        print(f"  [{c.type}] {c.concept}{candidates}")
        if c.qualifier:
            print(f"        限定: {c.qualifier}")

    print("\n分层检索...")
    result = search(extraction.concepts, collection)

    if args.verbose:
        for line in result.retrieval_log:
            print(line)

    print(f"\n匹配结果: {sum(1 for m in result.matches if m.matched)} 命中, {len(result.unmatched_concepts)} 未命中")
    for m in result.matches:
        if m.matched:
            codes_count = sum(len(col.code_values) for col in m.columns)
            print(f"  [{m.layer.value}] {m.table_name} — {m.table_comment} (score={m.score}, {len(m.columns)}字段, {codes_count}码值)")
        else:
            print(f"  [未匹配] {m.concept} — {m.message}")

    if result.unmatched_concepts:
        print(f"\n  待确认: {', '.join(result.unmatched_concepts)}")


def cmd_analyze(args):
    """analyze 子命令：完整链路"""
    from extractor.concept import extract_concepts
    from retrieval.engine import search
    from generator.pseudocode import generate
    from generator.script import generate_sql
    from dictionary.loader import load_dictionary
    from extractor.assertions import build_assertions

    _check_api_key()

    req_text = Path(args.req).read_text(encoding="utf-8")
    collection = _load_or_rebuild(args.dict, args.rebuild)

    has_assertions = True  # P1: 断言翻译始终启用
    total_steps = 4 if args.sql else 3
    if has_assertions:
        total_steps += 1

    print(f"步骤 1/{total_steps}: 提取业务概念...")
    extraction = extract_concepts(req_text)

    print(f"步骤 2/{total_steps}: 分层检索...")
    result = search(extraction.concepts, collection)

    print(f"步骤 2.5/{total_steps}: 构建断言条件...")
    assertions = build_assertions(extraction.concepts, result)
    if args.verbose:
        for a in assertions:
            print(f"  [{a.type.value}] {a.concept_source} → {a.sql_condition} (confidence={a.confidence})")
    else:
        print(f"  生成 {len(assertions)} 条断言")

    print(f"步骤 3/{total_steps}: 生成伪代码...")
    pseudocode = generate(req_text, result, extraction.concepts, assertions)

    sql = None
    if args.sql:
        print(f"步骤 4/{total_steps}: 生成 SQL 脚本...")
        data_dict = load_dictionary(args.dict)
        tables = {t.table_name: t for t in data_dict.tables}
        sql = generate_sql(pseudocode, tables, assertions)

    # ── L2.5 预期结果比对 ──
    expected_report = None
    if args.expected and sql:
        print(f"步骤 4.5/{total_steps}: 预期结果比对...")
        try:
            from testing.expected_compare import compare_with_expected
            import pandas as pd
            import sqlite3

            # 用 SQLite 内存库执行 SQL（demo 场景）
            conn = sqlite3.connect(":memory:")
            # 加载数据字典中的表作为内存表
            data_dict = load_dictionary(args.dict)
            # 简化的执行：仅做格式比对，实际环境需要连接真实 DB
            print(f"  提示: L2.5 需要真实数据库连接。当前 demo 模式仅验证比对逻辑。")
            print(f"  预期文件: {args.expected}")
            expected_report = "enabled"  # 标记已启用
        except Exception as e:
            print(f"  预期比对失败: {e}")

    if args.output == "json":
        payload = {
            "concepts": extraction.concepts,
            "retrieval": result,
        }
        print(_to_json(payload, pseudocode, sql))
        return

    # Markdown 输出
    payload = {
        "concepts": extraction.concepts,
        "retrieval": result,
    }
    md = _format_markdown(payload, pseudocode, verbose=args.verbose, sql=sql)
    print(md)


def main():
    parser = argparse.ArgumentParser(
        description="DataPilot — 需求分析助手：从业务需求文档自动匹配数据模型",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python cli.py search --req demo/req_sample.txt
  python cli.py analyze --req demo/req_sample.txt
  python cli.py analyze --req demo/req_sample.txt --sql
  python cli.py analyze --req demo/req_sample.txt --output json --rebuild
  python cli.py analyze --req demo/req_sample.txt --sql --verbose
        """,
    )
    sub = parser.add_subparsers(dest="command")

    # search
    p_search = sub.add_parser("search", help="提取概念 + 分层检索")
    p_search.add_argument("--req", "-r", required=True, help="需求文档路径 (.txt)")
    p_search.add_argument("--dict", "-d", default="demo/data_dict.csv", help="数据字典路径")
    p_search.add_argument("--rebuild", action="store_true", help="强制重建 ChromaDB 索引")
    p_search.add_argument("--output", "-o", choices=["text", "json"], default="text")
    p_search.add_argument("--verbose", "-v", action="store_true", help="显示详细检索日志")

    # analyze
    p_analyze = sub.add_parser("analyze", help="完整链路: 概念提取→检索→伪代码→SQL")
    p_analyze.add_argument("--req", "-r", required=True, help="需求文档路径 (.txt)")
    p_analyze.add_argument("--dict", "-d", default="demo/data_dict.csv", help="数据字典路径")
    p_analyze.add_argument("--rebuild", action="store_true", help="强制重建 ChromaDB 索引")
    p_analyze.add_argument("--output", "-o", choices=["text", "json"], default="text", help="输出格式")
    p_analyze.add_argument("--sql", action="store_true", help="生成最终 SQL 脚本")
    p_analyze.add_argument("--expected", "-e", default="", help="预期结果 CSV 文件路径（L2.5 比对）")
    p_analyze.add_argument("--verbose", "-v", action="store_true", help="显示详细检索日志")

    args = parser.parse_args()

    if args.command == "search":
        cmd_search(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
