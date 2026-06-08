/**
 * Auth API — login, get current user
 */

import { api } from './client';

export interface LoginParams {
  username: string;
  password: string;
}

export interface UserInfo {
  user_id: number;
  username: string;
  real_name: string;
  is_admin: boolean;
  department_id: number | null;
  department_path: string;
  visible_dept_ids: number[];
  business_line_codes: string[];
}

export interface LoginResult {
  token: string;
  user: UserInfo;
}

export const authApi = {
  /** Login with username + password, returns JWT token + user info */
  login: (params: LoginParams) =>
    api.post<LoginResult>('/api/auth/login', params),

  /** Get current user info from JWT token (for page refresh recovery) */
  me: () =>
    api.get<UserInfo>('/api/auth/me'),
};
