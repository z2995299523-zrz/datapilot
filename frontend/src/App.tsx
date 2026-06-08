/**
 * App — 路由 + Ant Design ConfigProvider (暗色主题)
 */

import { ConfigProvider, theme, App as AntApp } from 'antd';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';

import { themeConfig } from './theme';
import { AuthProvider, useAuth } from './auth/AuthContext';
import AppLayout from './components/Layout';
import LoginPage from './pages/LoginPage';
import DictionaryPage from './pages/DictionaryPage';
import AnalysisPage from './pages/AnalysisPage';
import ReconciliationPage from './pages/ReconciliationPage';
import ModelingPage from './pages/ModelingPage';
import AdminPage from './pages/AdminPage';

/** Route guard: redirect to /login if not authenticated */
function ProtectedRoute() {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}

/** Admin guard: redirect to /dictionary if not admin */
function AdminRoute() {
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return <Navigate to="/dictionary" replace />;
  }
  return <Outlet />;
}

export default function App() {
  return (
    <ConfigProvider
      theme={{
        ...themeConfig,
        algorithm: theme.darkAlgorithm,
      }}
    >
      <AntApp>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              {/* Public route — no layout */}
              <Route path="/login" element={<LoginPage />} />

              {/* Protected routes — wrapped in AppLayout */}
              <Route element={<ProtectedRoute />}>
                <Route element={<AppLayout />}>
                  <Route index element={<Navigate to="/dictionary" replace />} />
                  <Route path="dictionary" element={<DictionaryPage />} />
                  <Route path="analysis" element={<AnalysisPage />} />
                  <Route path="modeling" element={<ModelingPage />} />
                  <Route path="reconciliation" element={<ReconciliationPage />} />
                  {/* Admin-only routes */}
                  <Route element={<AdminRoute />}>
                    <Route path="admin" element={<AdminPage />} />
                  </Route>
                  <Route path="*" element={<Navigate to="/dictionary" replace />} />
                </Route>
              </Route>
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </AntApp>
    </ConfigProvider>
  );
}
