/**
 * Admin API — user/dept/business line/table mapping management
 */
import { api } from './client';

export interface AdminUser {
  id: number;
  username: string;
  real_name: string;
  department_id: number | null;
  department_name: string;
  is_admin: boolean;
  is_active: boolean;
  business_line_ids: number[];
  created_at: string;
}

export interface AdminDepartment {
  id: number;
  name: string;
  parent_id: number | null;
  path: string;
  level: number;
  is_active: boolean;
}

export interface AdminBusinessLine {
  id: number;
  name: string;
  code: string;
  description: string;
  is_active: boolean;
}

export interface AdminTableLineMapping {
  table_name: string;
  business_line_id: number;
}

export const adminApi = {
  // Users
  listUsers: () => api.get<AdminUser[]>('/api/admin/users'),
  createUser: (data: {
    username: string; password: string; real_name: string;
    department_id: number; business_line_ids?: number[]; is_admin?: boolean;
  }) => api.post('/api/admin/users', data),
  updateUser: (id: number, data: Record<string, unknown>) =>
    api.put(`/api/admin/users/${id}`, data),

  // Departments
  listDepartments: () => api.get<AdminDepartment[]>('/api/admin/departments'),
  createDepartment: (data: { name: string; parent_id?: number | null }) =>
    api.post('/api/admin/departments', data),
  updateDepartment: (id: number, data: Record<string, unknown>) =>
    api.put(`/api/admin/departments/${id}`, data),

  // Business Lines
  listBusinessLines: () => api.get<AdminBusinessLine[]>('/api/admin/business-lines'),
  createBusinessLine: (data: { name: string; code: string; description?: string }) =>
    api.post('/api/admin/business-lines', data),

  // Table-Line Mappings
  listTableLineMappings: () => api.get<AdminTableLineMapping[]>('/api/admin/table-line-mappings'),
  addTableLineMapping: (data: { table_name: string; business_line_id: number }) =>
    api.post('/api/admin/table-line-mappings', data),
  removeTableLineMapping: (tableName: string, lineId: number) =>
    api.delete(`/api/admin/table-line-mappings/${encodeURIComponent(tableName)}/${lineId}`),
};
