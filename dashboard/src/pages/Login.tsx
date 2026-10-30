import { useState } from 'react';
import { App as AntdApp, Button, Form, Input, Typography } from 'antd';
import {
  ApiOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Navigate, useNavigate } from 'react-router-dom';

import { isLogin, login } from '../services/auth';

interface LoginForm {
  username: string;
  password: string;
}

const HIGHLIGHTS = [
  { icon: <ThunderboltOutlined />, title: '多智能体编排', desc: '按意图路由到问答、审查、批改等能力' },
  { icon: <ApiOutlined />, title: '全链路可观测', desc: 'trace_id 贯穿请求，调用与审计一键回溯' },
  { icon: <SafetyCertificateOutlined />, title: '租户级隔离', desc: 'JWT 身份 + RBAC 权限，数据严格按租户二分' },
];

/** 登录页：对接 POST /api/v1/auth/login，账号密码由后端 RBAC 体系校验 */
export default function Login() {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const [submitting, setSubmitting] = useState(false);

  if (isLogin()) {
    return <Navigate to="/dashboard" replace />;
  }

  const onFinish = async (values: LoginForm) => {
    setSubmitting(true);
    try {
      const session = await login(values.username.trim(), values.password);
      message.success(`欢迎回来，${session.user.name || session.user.username}`);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      message.error(err instanceof Error ? err.message : '登录失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-shell">
        <aside className="login-brand">
          <div className="login-brand-logo">AP</div>
          <Typography.Title level={2} className="login-brand-title">
            多租户多智能体协作平台
          </Typography.Title>
          <Typography.Paragraph className="login-brand-desc">
            统一管理智能体、会话、工具与权限，让每一次调用都可观测、可审计。
          </Typography.Paragraph>
          <ul className="login-brand-list">
            {HIGHLIGHTS.map((item) => (
              <li key={item.title}>
                <span className="login-brand-icon">{item.icon}</span>
                <div>
                  <div className="login-brand-item-title">{item.title}</div>
                  <div className="login-brand-item-desc">{item.desc}</div>
                </div>
              </li>
            ))}
          </ul>
        </aside>

        <section className="login-panel">
          <div className="login-panel-head">
            <Typography.Title level={4} style={{ marginBottom: 4 }}>
              登录控制台
            </Typography.Title>
            <Typography.Text type="secondary">请使用平台账号登录，凭证由后端统一校验</Typography.Text>
          </div>

          <Form<LoginForm> name="login" size="large" onFinish={onFinish} autoComplete="off">
            <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
              <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
            </Form.Item>
            <Form.Item style={{ marginBottom: 12 }}>
              <Button type="primary" htmlType="submit" block loading={submitting}>
                登录
              </Button>
            </Form.Item>
          </Form>

          <Typography.Text type="secondary" className="login-tip">
            登录成功或失败都会写入登录审计日志；多次失败请检查账号状态。
          </Typography.Text>
        </section>
      </div>
    </div>
  );
}
