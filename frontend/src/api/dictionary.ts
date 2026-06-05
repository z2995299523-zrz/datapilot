/**
 * 数据字典 API 调用
 */

import { api } from './client';

export interface IndexStatus {
  ready: boolean;
  count: number;
  collection: string;
  error: string;
}

export interface UploadResult {
  success: boolean;
  layers: string[];
  total_rows: number;
  collection_count: number;
  saved_path: string;
  error: string;
}

export const dictionaryApi = {
  /** 上传数据字典文件并构建索引 */
  upload: async (file: File): Promise<UploadResult> => {
    const form = new FormData();
    form.append('file', file);
    const { data } = await api.post<UploadResult>('/api/dictionary/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  },

  /** 查询 ChromaDB 索引状态 */
  status: async (): Promise<IndexStatus> => {
    const { data } = await api.get<IndexStatus>('/api/dictionary/status');
    return data;
  },
};
