"""
断言翻译器 — 将业务概念 + 检索到的码值翻译为 SQL WHERE 条件

这是 DataPilot 的核心壁垒：把"活跃客户"翻译成 cust_status='01'。

输入: concepts (BusinessConcept) + retrieval (RetrievalResult)
输出: list[Assertion] — 确定性的 SQL WHERE 条件

设计原则:
  - 纯确定性代码（无 LLM 调用），100% 可预测
  - 高置信度匹配：概念名精确匹配码值 meaning → confidence=0.9+
  - 中置信度匹配：概念名与列名/注释匹配 → confidence=0.7
  - 未命中 → 不产生 Assertion（不猜测，避免错误条件）
"""
from models import (
    BusinessConcept, ConceptType, RetrievalResult,
    Assertion, AssertionType, CodeMapping,
)


def build_assertions(
    concepts: list[BusinessConcept],
    retrieval: RetrievalResult,
) -> list[Assertion]:
    """从业务概念和检索结果构建断言列表

    Args:
        concepts: 提取的业务概念列表
        retrieval: 分层检索结果

    Returns:
        断言列表，每个断言对应一个可执行的 SQL WHERE 条件
    """
    assertions: list[Assertion] = []

    # 构建概念→匹配表 的快速索引
    match_map: dict[str, list] = {}
    for m in retrieval.matches:
        if m.matched and m.table_name:
            match_map.setdefault(m.concept, []).append(m)

    for concept in concepts:
        matches = match_map.get(concept.concept, [])

        # ── 码值断言 ──
        if concept.type in (ConceptType.ENTITY, ConceptType.CONDITION):
            code_assertions = _build_code_assertions(concept, matches)
            assertions.extend(code_assertions)

        # ── 时间断言 ──
        if concept.type == ConceptType.TIME_RANGE:
            time_assertion = _build_time_assertion(concept, matches)
            if time_assertion:
                assertions.append(time_assertion)

        # ── 聚合断言 ──
        if concept.type == ConceptType.METRIC:
            agg_assertion = _build_aggregation_assertion(concept, matches)
            if agg_assertion:
                assertions.append(agg_assertion)

    return assertions


def _build_code_assertions(
    concept: BusinessConcept,
    matches: list,
) -> list[Assertion]:
    """构建码值断言: '活跃客户' + cust_status{01=活跃} → cust_status='01'"""
    results = []

    for match in matches:
        for col in match.columns:
            if not col.code_values:
                continue

            for code in col.code_values:
                # 精确包含匹配: concept 名包含在 meaning 中，或 meaning 包含在 concept 名中
                if _is_code_match(concept.concept, code):
                    sql_cond = f"{col.name} = '{code.value}'"
                    results.append(Assertion(
                        type=AssertionType.CODE,
                        column=col.name,
                        operator="=",
                        value=code.value,
                        concept_source=concept.concept,
                        table=match.table_name or "",
                        confidence=0.95,
                        sql_condition=sql_cond,
                    ))
                # 也尝试用 qualifier 做匹配
                elif concept.qualifier and code.meaning and code.meaning in concept.qualifier:
                    sql_cond = f"{col.name} = '{code.value}'"
                    results.append(Assertion(
                        type=AssertionType.CODE,
                        column=col.name,
                        operator="=",
                        value=code.value,
                        concept_source=concept.concept,
                        table=match.table_name or "",
                        confidence=0.85,
                        sql_condition=sql_cond,
                    ))

    return results


def _is_code_match(concept_name: str, code: CodeMapping) -> bool:
    """判断概念名是否匹配某个码值 meaning

    支持：双向子串匹配 + 关键词提取
    - "活跃客户" 中包含 "活跃" ←→ code.meaning="活跃" → 匹配
    - "正常" ←→ code.meaning="正常情况" → 匹配
    """
    if not code.meaning:
        return False
    # 双向子串匹配
    if code.meaning in concept_name or concept_name in code.meaning:
        return True
    # 关键词 level: 提取 concept 中的关键词(>=2 chars)与 meaning 比较
    for i in range(len(concept_name) - 1):
        for j in range(i + 2, len(concept_name) + 1):
            keyword = concept_name[i:j]
            if keyword in code.meaning and len(keyword) >= 2:
                return True
    return False


def _build_time_assertion(
    concept: BusinessConcept,
    matches: list,
) -> Assertion | None:
    """构建时间断言: '近6个月' + qualifier → TimeAssertion

    从 qualifier 中提取 SQL 表达式；若无 qualifier，基于概念名推断通用模式。
    """
    sql_expr = ""

    # 优先使用 qualifier 中的 SQL 表达式
    if concept.qualifier:
        # qualifier 通常是 "trans_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)" 之类
        sql_expr = concept.qualifier

    # 尝试从匹配表中找日期列
    date_column = ""
    target_table = ""
    for match in matches:
        for col in match.columns:
            if _is_date_column(col.name, col.data_type):
                date_column = col.name
                target_table = match.table_name or ""
                break
        if date_column:
            break

    # 构建通用时间表达式
    if not sql_expr and date_column:
        sql_expr = _build_generic_time_expr(concept.concept)

    if sql_expr:
        return Assertion(
            type=AssertionType.TIME,
            column=date_column or _extract_column_from_qualifier(concept.qualifier),
            operator=">=",
            value=sql_expr,
            concept_source=concept.concept,
            table=target_table,
            confidence=0.90 if concept.qualifier else 0.60,
            sql_condition=sql_expr if " " in sql_expr
            else f"{date_column} >= {sql_expr}",
        )
    return None


def _is_date_column(name: str, data_type: str) -> bool:
    """判断是否为日期列"""
    name_lower = name.lower()
    dt_lower = data_type.lower()
    date_keywords = ["date", "time", "日期", "时间", "dt", "day", "month", "year"]
    return any(kw in name_lower for kw in date_keywords) or \
           any(kw in dt_lower for kw in ["date", "time", "timestamp"])


def _build_generic_time_expr(concept_name: str) -> str:
    """从概念名推断通用时间表达式"""
    import re
    # "近6个月" → DATE_SUB(NOW(), INTERVAL 6 MONTH)
    # "今年以来" → DATE_FORMAT(NOW(), '%Y-01-01')
    # "最近30天" → DATE_SUB(NOW(), INTERVAL 30 DAY)
    month_match = re.search(r'(\d+)\s*(个)?月', concept_name)
    if month_match:
        n = int(month_match.group(1))
        return f"DATE_SUB(NOW(), INTERVAL {n} MONTH)"

    day_match = re.search(r'(\d+)\s*天', concept_name)
    if day_match:
        n = int(day_match.group(1))
        return f"DATE_SUB(NOW(), INTERVAL {n} DAY)"

    return ""


def _extract_column_from_qualifier(qualifier: str) -> str:
    """从 qualifier 中提取列名，如 'cust_status=01' → 'cust_status'"""
    if not qualifier:
        return ""
    # 尝试提取 SQL 表达式中的列名（长分隔符优先，避免 "=" 误匹配 ">="）
    for sep in [" >=", " <=", " IN", " BETWEEN", " >", " <", " =", "=", ">=", "<=", ">", "<"]:
        if sep in qualifier:
            return qualifier.split(sep)[0].strip()
    return ""


def _build_aggregation_assertion(
    concept: BusinessConcept,
    matches: list,
) -> Assertion | None:
    """构建聚合断言: '交易金额' → SUM(txn_amt)

    从概念名推断聚合函数 (SUM/COUNT/AVG/MAX/MIN)
    """
    agg_func = _infer_agg_function(concept.concept)

    # 从匹配表中找合适的列
    # COUNT 可用任意列，SUM/AVG 需要数值列
    metric_column = ""
    target_table = ""
    for match in matches:
        for col in match.columns:
            if agg_func == "COUNT" or _is_numeric_column(col.data_type):
                metric_column = col.name
                target_table = match.table_name or ""
                break
        if metric_column:
            break

    if agg_func and metric_column:
        sql_expr = f"{agg_func}({metric_column})"
        return Assertion(
            type=AssertionType.AGG,
            column=metric_column,
            operator=agg_func,
            value=metric_column,
            concept_source=concept.concept,
            table=target_table,
            confidence=0.80,
            sql_condition=sql_expr,
        )

    return None


def _infer_agg_function(concept_name: str) -> str:
    """从概念名推断聚合函数（长关键词优先，避免"平均交易金额"被"金额"误匹配为SUM）"""
    # 按长度降序排列，长关键词优先匹配
    mapping = [
        ("平均交易金额", "AVG"),
        ("交易金额", "SUM"),
        ("客户数", "COUNT"),
        ("平均", "AVG"), ("均值", "AVG"),
        ("金额", "SUM"), ("总额", "SUM"),
        ("数量", "COUNT"), ("人数", "COUNT"),
        ("笔数", "COUNT"), ("统计", "COUNT"),
        ("最大", "MAX"), ("最高", "MAX"),
        ("最小", "MIN"), ("最低", "MIN"),
    ]
    for keyword, func in mapping:
        if keyword in concept_name:
            return func
    # 默认: 含"金额"等数值关键词 → SUM
    if any(kw in concept_name for kw in ["金额", "成本", "收入", "利润"]):
        return "SUM"
    return ""


def _is_numeric_column(data_type: str) -> bool:
    """判断是否为数值列"""
    dt_lower = data_type.lower()
    numeric_types = ["int", "decimal", "numeric", "float", "double", "number", "bigint", "smallint"]
    return any(t in dt_lower for t in numeric_types)
