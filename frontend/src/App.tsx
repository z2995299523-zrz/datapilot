/**
 * App — 路由 + Ant Design ConfigProvider (暗色主题)
 */

import { ConfigProvider, theme, App as AntApp } from 'antd';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import { themeConfig } from './theme';
import AppLayout from './components/Layout';
import DictionaryPage from './pages/DictionaryPage';
import AnalysisPage from './pages/AnalysisPage';
import ReconciliationPage from './pages/ReconciliationPage';

export default function App() {
  return (
    <ConfigProvider
      theme={{
        ...themeConfig,
        algorithm: theme.darkAlgorithm,
      }}
    >
      <AntApp>
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<Navigate to="/dictionary" replace />} />
              <Route path="dictionary" element={<DictionaryPage />} />
              <Route path="analysis" element={<AnalysisPage />} />
              <Route path="reconciliation" element={<ReconciliationPage />} />
              <Route path="*" element={<Navigate to="/dictionary" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  );
}
