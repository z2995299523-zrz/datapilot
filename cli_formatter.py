"""
CLI 输出格式化 — Markdown / JSON

从 cli.py 拆分，SRP: CLI 入口只管参数解析和流程编排，
格式化逻辑独立在此。

使用方式:
    # 新（推荐）: 直接导入格式化函数
    from cli_formatter import format_markdown, format_json

    # 旧（兼容）: cli.py 内部仍通过 _format_markdown / _to_json 别名调用
"""
import json


def format_markdown(result, pseudocode=None, verbose=False, sql=None):
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


def format_json(result, pseudocode=None, sql=None):
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
