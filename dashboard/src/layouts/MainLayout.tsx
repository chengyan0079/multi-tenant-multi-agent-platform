import { useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
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
import { Avatar, Button, Drawer, Grid, Layout, Menu, Typography } from 'antd';

import { getUser, logout } from '../services/auth';

const { Header, Sider, Content } = Layout;
const { useBreakpoint } = Grid;

/** 左侧菜单栏 */
const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '监控概览' },
  { key: '/agents', icon: <RobotOutlined />, label: '智能体管理' },
  { key: '/sessions', icon: <MessageOutlined />, label: '会话运行' },
  { key: '/tools', icon: <ToolOutlined />, label: '工具与插件' },
  { key: '/rbac', icon: <SafetyCertificateOutlined />, label: '权限中心' },
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
    <Layout style={{ height: '100%' }}>
      {!isMobile && (
        <Sider collapsible collapsed={collapsed} trigger={null} theme="dark" width={200}>
          <div className="app-logo">{collapsed ? 'AP' : 'Agent Platform'}</div>
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
            <Avatar size="small" icon={<UserOutlined />} />
            {!isMobile && (
              <>
                <Typography.Text>{user.username}</Typography.Text>
                <Typography.Text type="secondary">（{user.role}）</Typography.Text>
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
