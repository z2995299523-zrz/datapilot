/**
 * LoginPage — 全屏居中登录页
 *
 * 使用 Ant Design Card + Form 实现。
 * 成功登录后存储 token 到 localStorage 并跳转到 /dictionary。
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Form, Input, Button, Typography, Alert, theme } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { useAuth } from '../auth/AuthContext';

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();
  const { token: themeToken } = theme.useToken();

  const handleSubmit = async (values: { username: string; password: string }) => {
    setLoading(true);
    setError('');
    try {
      await login(values.username, values.password);
      navigate('/dictionary');
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || '登录失败，请检查用户名和密码';
      setError(detail);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        background: themeToken.colorBgLayout,
      }}
    >
      <Card style={{ width: 400, boxShadow: themeToken.boxShadow }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <span style={{ fontSize: 48 }}>📊</span>
          <Typography.Title
            level={3}
            style={{ marginTop: 12, marginBottom: 4, color: '#E0E3E8' }}
          >
            DataPilot
          </Typography.Title>
          <Typography.Text type="secondary">
            需求 → SQL 全链路分析引擎
          </Typography.Text>
        </div>

        {error && (
          <Alert
            message={error}
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
          />
        )}

        <Form onFinish={handleSubmit} size="large" autoComplete="off">
          <Form.Item
            name="username"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
