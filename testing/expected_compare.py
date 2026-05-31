"""
预期结果比对 — L2.5 测试层

用户上传预期数据集（CSV/JSON），将生成 SQL 的执行结果与预期数据做逐行逐列的差异分析。
差异报告作为 Diagnoser Agent 的输入，帮助 LLM 理解"不是语法错了，是逻辑偏了"。

用法:
    report = compare_with_expected(actual_df, "expected.csv", key_columns=["branch_id"])
"""
from pathlib import Path
import pandas as pd

from models import ExpectedComparisonReport, ValueDiff


def compare_with_expected(
    actual_df: pd.DataFrame,
    expected_path: str,
    key_columns: list[str] | None = None,
    compare_columns: list[str] | None = None,
    tolerance: float = 0.001,
) -> ExpectedComparisonReport:
    """将 SQL 执行结果与预期数据集逐行逐列比对

    Args:
        actual_df: SQL 实际执行结果
        expected_path: 预期数据 CSV/JSON 文件路径
        key_columns: 对齐键（如 ["branch_id", "year_month"]），None 时自动推断
        compare_columns: 比对的数值列，None 时使用所有公共数值列
        tolerance: 允许的相对偏差（默认 0.1%）

    Returns:
        ExpectedComparisonReport
    """
    expected_df = _load_expected(expected_path)

    total_expected = len(expected_df)
    total_actual = len(actual_df)

    # 自动推断键列和比对列
    if key_columns is None:
        key_columns = _infer_key_columns(expected_df, actual_df)
    if compare_columns is None:
        compare_columns = _infer_compare_columns(expected_df, actual_df, key_columns)

    # 标准化列名
    expected_df.columns = [c.strip().lower() for c in expected_df.columns]
    actual_cols = {c.strip().lower(): c for c in actual_df.columns}
    actual_df_renamed = actual_df.rename(columns=actual_cols)
    key_columns = [c.strip().lower() for c in key_columns]
    compare_columns = [c.strip().lower() for c in compare_columns]

    # ── 按键列对齐 ──
    expected_key_str = expected_df[key_columns].astype(str).agg("|".join, axis=1)
    actual_key_str = actual_df_renamed[key_columns].astype(str).agg("|".join, axis=1)

    expected_keys = set(expected_key_str)
    actual_keys = set(actual_key_str)

    missing_in_actual = sorted(expected_keys - actual_keys)
    extra_in_actual = sorted(actual_keys - expected_keys)

    # ── 对公共行做逐列偏差分析 ──
    common_keys = expected_keys & actual_keys
    value_diffs: list[ValueDiff] = []

    if common_keys:
        # 构造索引
        expected_indexed = expected_df.copy()
        expected_indexed["_key"] = expected_key_str
        expected_indexed = expected_indexed.set_index("_key")

        actual_indexed = actual_df_renamed.copy()
        actual_indexed["_key"] = actual_key_str
        actual_indexed = actual_indexed.set_index("_key")

        for key in sorted(common_keys):
            for col in compare_columns:
                if col not in expected_indexed.columns or col not in actual_indexed.columns:
                    continue
                try:
                    exp_val = float(expected_indexed.loc[key, col])
                    act_val = float(actual_indexed.loc[key, col])
                except (ValueError, TypeError, KeyError):
                    # 非数值列，逐字比对
                    exp_str = str(expected_indexed.loc[key, col])
                    act_str = str(actual_indexed.loc[key, col])
                    if exp_str != act_str:
                        value_diffs.append(ValueDiff(
                            key_values=key,
                            column=col,
                            expected_value=exp_str,
                            actual_value=act_str,
                            diff_percent=1.0,
                        ))
                    continue

                if exp_val == 0 and act_val == 0:
                    continue
                if exp_val == 0:
                    diff_pct = 1.0 if act_val != 0 else 0.0
                else:
                    diff_pct = abs(act_val - exp_val) / abs(exp_val)

                if diff_pct > tolerance:
                    value_diffs.append(ValueDiff(
                        key_values=key,
                        column=col,
                        expected_value=str(exp_val),
                        actual_value=str(act_val),
                        diff_percent=round(diff_pct, 4),
                    ))

    # ── 汇总 ──
    match_count = len(common_keys) - len({d.key_values for d in value_diffs})
    mismatch_count = len(missing_in_actual) + len(extra_in_actual) + len(value_diffs)
    overall_passed = (mismatch_count == 0)

    report = ExpectedComparisonReport(
        total_expected=total_expected,
        total_actual=total_actual,
        match_count=match_count,
        mismatch_count=mismatch_count,
        missing_in_actual=missing_in_actual,
        extra_in_actual=extra_in_actual,
        value_diffs=value_diffs,
        overall_passed=overall_passed,
    )
    report.summary = _build_summary(report)
    return report


def _load_expected(path: str) -> pd.DataFrame:
    """加载预期数据集（CSV 或 JSON）"""
    p = Path(path)
    if p.suffix.lower() in (".csv", ".txt"):
        return pd.read_csv(p, encoding="utf-8")
    elif p.suffix.lower() == ".json":
        return pd.read_json(p)
    else:
        raise ValueError(f"不支持的预期数据格式: {p.suffix}，仅支持 CSV/JSON")


def _infer_key_columns(
    expected_df: pd.DataFrame,
    actual_df: pd.DataFrame,
) -> list[str]:
    """推断对齐键列：找两个表中共有的非数值列"""
    common = [c for c in expected_df.columns if c in actual_df.columns]
    # 优先非数值列作为键
    non_numeric = [
        c for c in common
        if expected_df[c].dtype == "object" or expected_df[c].dtype == "string"
    ]
    if non_numeric:
        return non_numeric[:2]  # 最多 2 个键列
    return common[:1] if common else [expected_df.columns[0]]


def _infer_compare_columns(
    expected_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    key_columns: list[str],
) -> list[str]:
    """推断比对列：排除键列的数值列"""
    common = [c for c in expected_df.columns if c in actual_df.columns]
    return [c for c in common if c not in key_columns]


def _build_summary(report: ExpectedComparisonReport) -> str:
    """生成比对摘要"""
    parts = []
    if report.missing_in_actual:
        parts.append(f"缺失 {len(report.missing_in_actual)} 行")
    if report.extra_in_actual:
        parts.append(f"多余 {len(report.extra_in_actual)} 行")
    if report.value_diffs:
        parts.append(f"{len(report.value_diffs)} 处数值偏差")
    if not parts:
        parts.append("完全匹配")
    return f"预期 {report.total_expected} 行 vs 实际 {report.total_actual} 行: " + "，".join(parts)
