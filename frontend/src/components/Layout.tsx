/**
 * 主布局 — 侧边栏导航 + 内容区
 *
 * 三页面结构:
 *   /dictionary      — 数据字典管理
 *   /analysis        — 需求分析
 *   /reconciliation  — 修复闭环
 */

import { useState, useEffect } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Layout, Menu, Typography, Badge } from 'antd';
import {
  BookOutlined,
  SearchOutlined,
  BuildOutlined,
  ToolOutlined,
  ApiOutlined,
} from '@ant-design/icons';

import { dictionaryApi } from '../api/dictionary';

const { Sider, Content } = Layout;

const menuItems = [
  { key: '/dictionary', icon: <BookOutlined />, label: '数据字典管理' },
  { key: '/analysis', icon: <SearchOutlined />, label: '需求分析' },
  { key: '/modeling', icon: <BuildOutlined />, label: '数仓建模' },
  { key: '/reconciliation', icon: <ToolOutlined />, label: '修复闭环' },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const [indexReady, setIndexReady] = useState(false);
  const [indexCount, setIndexCount] = useState(0);

  // 检查索引状态
  useEffect(() => {
    dictionaryApi.status().then((res) => {
      setIndexReady(res.ready);
      setIndexCount(res.count);
    });
  }, []);

  // 路由重定向由 App.tsx 中的 <Navigate> 处理

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        width={220}
        style={{
          borderRight: '1px solid #2D333B',
          overflow: 'auto',
        }}
      >
        {/* Logo */}
        <div
          style={{
            padding: '20px 20px 12px',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <span style={{ fontSize: 22 }}>📊</span>
          <div>
            <Typography.Text
              strong
              style={{ color: '#E0E3E8', fontSize: 16, display: 'block' }}
            >
              DataPilot
            </Typography.Text>
            <Typography.Text style={{ color: '#6E7681', fontSize: 11 }}>
              需求→SQL 全链路引擎
            </Typography.Text>
          </div>
        </div>

        {/* Nav */}
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderInlineEnd: 'none', marginTop: 8 }}
          theme="dark"
        />

        {/* Status footer */}
        <div
          style={{
            position: 'absolute',
            bottom: 0,
            left: 0,
            right: 0,
            padding: '12px 20px',
            borderTop: '1px solid #2D333B',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <Badge status={indexReady ? 'success' : 'error'} />
            <Typography.Text style={{ color: '#9099A4', fontSize: 12 }}>
              {indexReady ? `索引就绪 (${indexCount})` : '索引未构建'}
            </Typography.Text>
          </div>
          <Typography.Text style={{ color: '#505A66', fontSize: 11 }}>
            <ApiOutlined /> FastAPI :8000
          </Typography.Text>
        </div>
      </Sider>

      <Content style={{ padding: '32px 40px', overflow: 'auto' }}>
        <Outlet />
      </Content>
    </Layout>
  );
}
