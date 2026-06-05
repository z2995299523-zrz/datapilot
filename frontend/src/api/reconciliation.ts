/**
 * 修复闭环 API 调用
 */

import { api } from './client';

export interface ReconciliationRequest {
  original_sql: string;
  requirement_text?: string;
  db_conn_str?: string;
  max_loops?: number;
  dict_path?: string | null;
  expected_csv_path?: string | null;
}

export interface ReconciliationResult {
  status: string;
  loop_count: number;
  max_loops: number;
  error_message: string;
  fix_history: Record<string, unknown>[];
  quality_report: Record<string, unknown> | null;
  comparison_report: Record<string, unknown> | null;
  diagnosis_report: Record<string, unknown> | null;
}

export interface TestsRequest {
  original_sql: string;
  db_conn_str: string;
  dict_path?: string | null;
}

export const reconciliationApi = {
  /** 运行完整修复闭环 */
  run: async (req: ReconciliationRequest): Promise<ReconciliationResult> => {
    const { data } = await api.post<ReconciliationResult>('/api/reconciliation/run', req);
    return data;
  },

  /** 仅运行 L1 质量测试 */
  tests: async (req: TestsRequest): Promise<Record<string, unknown>> => {
    const { data } = await api.post('/api/reconciliation/tests', req);
    return data;
  },
};
