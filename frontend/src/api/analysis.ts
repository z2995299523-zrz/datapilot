/**
 * 需求分析 API 调用
 */

import { api } from './client';

export interface AnalysisResult {
  requirement_text: string;
  extraction: Record<string, unknown> | null;
  retrieval: Record<string, unknown> | null;
  pseudocode: Record<string, unknown> | null;
  sql: string;
  error: string;
}

export interface CompareRequest {
  sql: string;
  db_conn_str: string;
  expected_csv: string; // base64
}

export interface CompareResult {
  overall_passed: boolean;
  total_expected: number;
  total_actual: number;
  match_count: number;
  mismatch_count: number;
  summary: string;
  missing_in_actual: Record<string, unknown>[];
  extra_in_actual: Record<string, unknown>[];
  value_diffs: ValueDiff[];
  actual_preview: Record<string, unknown>[];
  error?: string;
}

export interface ValueDiff {
  key_values: string;
  column: string;
  expected_value: string;
  actual_value: string;
  diff_percent: number;
}

export const analysisApi = {
  /** 全链路分析：概念提取 → 检索 → 伪代码 → SQL */
  full: async (requirementText: string, generateSql: boolean = true, dictPath?: string): Promise<AnalysisResult> => {
    const { data } = await api.post<AnalysisResult>('/api/analysis/full', {
      requirement_text: requirementText,
      generate_sql: generateSql,
      dict_path: dictPath || null,
    });
    return data;
  },

  /** 预期结果比对 */
  compare: async (req: CompareRequest): Promise<CompareResult> => {
    const { data } = await api.post<CompareResult>('/api/analysis/compare', req);
    return data;
  },
};
