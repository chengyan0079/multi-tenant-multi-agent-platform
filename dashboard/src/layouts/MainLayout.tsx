import { useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  ApiOutlined,
  DashboardOutlined,
  FileSearchOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MessageOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Avatar, Button, Drawer, Grid, Layout, Menu, Tag, Typography } from 'antd';

import { getUser, logout } from '../services/auth';

const { Header, Sider, Content } = Layout;
const { useBreakpoint } = Grid;

/** 左侧菜单栏 */
const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '监控概览' },
  { key: '/agents', icon: <RobotOutlined />, label: '智能体管理' },
  { key: '/sessions', icon: <MessageOutlined />, label: '会话运行' },
  { key: '/tools', icon: <ToolOutlined />, label: '工具与插件' },
  { key: '/models', icon: <ApiOutlined />, label: '模型注册表' },
  {
    key: '/rbac',
    icon: <SafetyCertificateOutlined />,
    label: '权限中心',
    children: [
      { key: '/users', label: '用户管理' },
      { key: '/tenants', label: '租户管理' },
      { key: '/roles', label: '角色管理' },
      { key: '/menus', label: '菜单管理' },
    ],
  },
  { key: '/config', icon: <SettingOutlined />, label: '配置中心' },
  { key: '/audit', icon: <FileSearchOutlined />, label: '审计日志' },
];

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const screens = useBreakpoint();
  // 窄屏（< lg，即 <992px）用抽屉菜单；宽屏用可折叠侧边栏
  const isMobile = screens.lg === false;

  const navigate = useNavigate();
  const location = useLocation();
  const user = getUser();

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const onMenuClick = ({ key }: { key: string }) => {
    navigate(key);
    if (isMobile) {
      setDrawerOpen(false);
    }
  };

  const menuNode = (
    <Menu
      theme={isMobile ? 'light' : 'dark'}
      mode="inline"
      selectedKeys={[location.pathname]}
      items={menuItems}
      onClick={onMenuClick}
    />
  );

  return (
    <Layout className="app-shell">
      {!isMobile && (
        <Sider collapsible collapsed={collapsed} trigger={null} theme="dark" width={200}>
          <div className="app-logo">{collapsed ? '智' : '智能体平台'}</div>
          {menuNode}
        </Sider>
      )}

      {isMobile && (
        <Drawer
          title="导航菜单"
          placement="left"
          width={220}
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
        >
          {menuNode}
        </Drawer>
      )}

      <Layout>
        <Header className="app-header">
          <Button
            type="text"
            aria-label="切换菜单"
            icon={isMobile || collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => (isMobile ? setDrawerOpen(true) : setCollapsed(!collapsed))}
          />
          <div className="app-header-right">
            <Avatar size="small" style={{ background: '#1677ff' }} icon={<UserOutlined />} />
            {!isMobile && (
              <>
                <Typography.Text strong>{user.name || user.username}</Typography.Text>
                <Tag color="blue" style={{ marginInlineEnd: 0 }}>
                  {user.role}
                </Tag>
                {user.tenantName ? <Tag style={{ marginInlineEnd: 0 }}>{user.tenantName}</Tag> : null}
              </>
            )}
            <Button type="text" icon={<LogoutOutlined />} onClick={handleLogout}>
              {!isMobile && '退出登录'}
            </Button>
          </div>
        </Header>
        <Content className="app-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
