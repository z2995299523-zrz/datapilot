/**
 * Axios 实例 — 统一 baseURL、超时、错误处理
 */

import axios from 'axios';

const API_BASE = 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 180_000, // 分析可能耗时 30-60s
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.code === 'ECONNABORTED') {
      console.error('请求超时');
    } else if (!error.response) {
      console.error('无法连接后端服务, 请确认 python -m uvicorn backend.main:app --port 8000 已启动');
    }
    return Promise.reject(error);
  },
);
