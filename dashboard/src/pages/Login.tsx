import { App as AntdApp, Button, Card, Form, Input, Typography } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { Navigate, useNavigate } from 'react-router-dom';

import { DEFAULT_ACCOUNT, isLogin, login } from '../services/auth';

interface LoginForm {
  username: string;
  password: string;
}

/**
 * 登录页：仅账号 + 密码，无验证码、无注册、无修改密码入口。
 * 默认账号 admin / admin。
 */
export default function Login() {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();

  if (isLogin()) {
    return <Navigate to="/dashboard" replace />;
  }

  const onFinish = (values: LoginForm) => {
    const result = login(values.username, values.password);
    if (result.ok) {
      message.success('登录成功');
      navigate('/dashboard', { replace: true });
    } else {
      message.error(result.message);
    }
  };

  return (
    <div className="login-page">
      <Card style={{ width: '100%', maxWidth: 380 }} title="Agent Platform 控制台">
        <Form<LoginForm>
          name="login"
          size="large"
          initialValues={DEFAULT_ACCOUNT}
          onFinish={onFinish}
          autoComplete="off"
        >
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
          <Form.Item style={{ marginBottom: 8 }}>
            <Button type="primary" htmlType="submit" block>
              登录
            </Button>
          </Form.Item>
          <Typography.Text type="secondary">
            默认账号：{DEFAULT_ACCOUNT.username} / {DEFAULT_ACCOUNT.password}
          </Typography.Text>
        </Form>
      </Card>
    </div>
  );
}
