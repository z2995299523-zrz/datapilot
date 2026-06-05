/**
 * 数仓建模 API 调用
 */

import { api } from './client';

export interface ModelingResult {
  source_name: string;
  layers: Record<string, string[]>;
  classifications: Record<string, ClassificationEntry>;
  relationships: Relationship[];
  code_columns: CodeCandidate[];
  schemas: SchemaDef[];
  quality_issues: QualityIssue[];
  total_tables: number;
  llm_used: boolean;
  metadata: Record<string, unknown>;
}

export interface ClassificationEntry {
  table_name: string;
  role: string;
  confidence: number;
  reasoning: string;
  layer: string | null;
  score_detail: Record<string, number>;
}

export interface Relationship {
  source_table: string;
  source_column: string;
  target_table: string;
  target_column: string;
  confidence: number;
  detection_method: string;
}

export interface CodeCandidate {
  column_name: string;
  table_name: string;
  confidence: number;
  detection_reason: string;
  candidate_values: { value: string; meaning: string }[];
}

export interface SchemaDef {
  name: string;
  schema_type: string;
  tables: string[];
  relationships: Relationship[];
  description: string;
}

export interface QualityIssue {
  rule: string;
  severity: string;
  table: string;
  column: string;
  description: string;
  suggestion: string;
}

export interface ModelingRequest {
  source_name: string;
  tables: Record<string, unknown>[];
  enable_llm: boolean;
  detect_codes: boolean;
  validate_quality: boolean;
}

export interface SchemaUploadResult {
  success: boolean;
  source_name: string;
  tables_detected: number;
  columns_detected: number;
  saved_path: string;
  error: string;
}

export const modelingApi = {
  upload: async (file: File): Promise<SchemaUploadResult> => {
    const form = new FormData();
    form.append('file', file);
    const { data } = await api.post<SchemaUploadResult>('/api/modeling/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },

  analyze: async (req: ModelingRequest): Promise<ModelingResult> => {
    const { data } = await api.post<ModelingResult>('/api/modeling/analyze', req);
    return data;
  },
};
