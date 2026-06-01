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
from cli_formatter import format_markdown, format_json

# 向后兼容别名（旧代码无需修改）
_format_markdown = format_markdown
_to_json = format_json


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
        total_steps += 0.5
        print(f"步骤 4.5/{total_steps}: 预期结果比对...")
        try:
            from testing.expected_compare import compare_with_expected
            import pandas as pd
            import sqlite3

            db_path = args.db
            if not db_path:
                print(f"  提示: 需要 --db 参数指定 SQLite 数据库路径才能执行比对")
                print(f"  预期文件: {args.expected}")
            elif not Path(db_path).exists():
                print(f"  错误: 数据库文件不存在: {db_path}")
            else:
                conn = sqlite3.connect(db_path)
                try:
                    actual_df = pd.read_sql_query(sql, conn)
                    report = compare_with_expected(actual_df, args.expected)
                    expected_report = report
                    print(f"  预期 {report.total_expected} 行 vs 实际 {report.total_actual} 行")
                    if report.overall_passed:
                        print(f"  ✅ 完全匹配 ({report.match_count} 行)")
                    else:
                        print(f"  ❌ {report.mismatch_count} 处差异")
                        if report.missing_in_actual:
                            print(f"     缺失行: {', '.join(report.missing_in_actual[:5])}")
                        if report.extra_in_actual:
                            print(f"     多余行: {', '.join(report.extra_in_actual[:5])}")
                        if report.value_diffs:
                            print(f"     数值偏差: {len(report.value_diffs)} 处")
                finally:
                    conn.close()
        except Exception as e:
            print(f"  预期比对失败: {e}")

    if args.output == "json":
        payload = {
            "concepts": extraction.concepts,
            "retrieval": result,
        }
        output = _to_json(payload, pseudocode, sql)
        # 如果是 JSON 输出且有预期比对报告，注入到输出中
        if expected_report is not None:
            import json as _json
            output_dict = _json.loads(output)
            output_dict["expected_comparison"] = expected_report.model_dump()
            output = _json.dumps(output_dict, ensure_ascii=False, indent=2)
        print(output)
        return

    # Markdown 输出
    payload = {
        "concepts": extraction.concepts,
        "retrieval": result,
    }
    md = _format_markdown(payload, pseudocode, verbose=args.verbose, sql=sql)

    # L2.5 预期比对结果追加到 Markdown
    if expected_report is not None:
        md += "\n## 预期结果比对 (L2.5)\n\n"
        md += f"预期 {expected_report.total_expected} 行 vs 实际 {expected_report.total_actual} 行\n\n"
        if expected_report.overall_passed:
            md += f"✅ **完全匹配** ({expected_report.match_count} 行)\n\n"
        else:
            md += f"❌ **{expected_report.mismatch_count} 处差异**\n\n"
            if expected_report.missing_in_actual:
                md += f"- 缺失行: {', '.join(expected_report.missing_in_actual[:10])}\n"
            if expected_report.extra_in_actual:
                md += f"- 多余行: {', '.join(expected_report.extra_in_actual[:10])}\n"
            if expected_report.value_diffs:
                md += "- 数值偏差:\n"
                for diff in expected_report.value_diffs[:10]:
                    md += f"  - `{diff.key_values}`.{diff.column}: "
                    md += f"预期={diff.expected_value}, 实际={diff.actual_value}, "
                    md += f"偏差={diff.diff_percent:.1%}\n"
        md += f"\n{expected_report.summary}\n\n"

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
    p_analyze.add_argument("--db", default="", help="SQLite 数据库路径（执行 SQL 并比对预期结果）")
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
