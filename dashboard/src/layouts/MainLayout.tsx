import { useMemo, useState, type ReactNode } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { ProLayout, type MenuDataItem } from '@ant-design/pro-components';
import {
  ApiOutlined,
  AppstoreOutlined,
  AuditOutlined,
  CommentOutlined,
  DashboardOutlined,
  DeploymentUnitOutlined,
  ExceptionOutlined,
  FileOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  FormOutlined,
  KeyOutlined,
  LoginOutlined,
  MailOutlined,
  MenuOutlined,
  MessageOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  SettingOutlined,
  TeamOutlined,
  ToolOutlined,
  UnorderedListOutlined,
  UploadOutlined,
  UserOutlined,
  ProfileOutlined,
} from '@ant-design/icons';

import { getSession, getUser, logout, type MenuNode } from '../services/auth';
import { useThemeMode } from '../theme/ThemeProvider';
import AppStatusBar from './AppStatusBar';

const PRODUCT_NAME = '多租户多智能体协作平台';

/** 后端 menu.icon 字符串 → antd 图标组件；未匹配用默认图标兜底。 */
const ICONS: Record<string, ReactNode> = {
  DashboardOutlined: <DashboardOutlined />,
  MessageOutlined: <MessageOutlined />,
  MailOutlined: <MailOutlined />,
  SendOutlined: <SendOutlined />,
  ExceptionOutlined: <ExceptionOutlined />,
  RobotOutlined: <RobotOutlined />,
  ToolOutlined: <ToolOutlined />,
  DeploymentUnitOutlined: <DeploymentUnitOutlined />,
  SettingOutlined: <SettingOutlined />,
  FileSearchOutlined: <FileSearchOutlined />,
  FileOutlined: <FileOutlined />,
  FolderOpenOutlined: <FolderOpenOutlined />,
  SafetyCertificateOutlined: <SafetyCertificateOutlined />,
  TeamOutlined: <TeamOutlined />,
  UserOutlined: <UserOutlined />,
  KeyOutlined: <KeyOutlined />,
  MenuOutlined: <MenuOutlined />,
  CommentOutlined: <CommentOutlined />,
  FileTextOutlined: <FileTextOutlined />,
  LoginOutlined: <LoginOutlined />,
  ApiOutlined: <ApiOutlined />,
  FormOutlined: <FormOutlined />,
  AuditOutlined: <AuditOutlined />,
  ProfileOutlined: <ProfileOutlined />,
  UploadOutlined: <UploadOutlined />,
  UnorderedListOutlined: <UnorderedListOutlined />,
};

/** 由后端下发的菜单树构建 ProLayout 的 route（菜单已按当前身份 scope 过滤，显隐自动贴合权限）。 */
function buildMenuRoutes(menus: MenuNode[]): MenuDataItem[] {
  return menus.map((m) => ({
    path: m.path,
    name: m.name,
    icon: ICONS[m.icon ?? ''] ?? <AppstoreOutlined />,
    routes: m.children && m.children.length ? buildMenuRoutes(m.children) : undefined,
  })) as MenuDataItem[];
}

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { isDark } = useThemeMode();

  const user = getUser();
  const session = getSession();
  const menuRoutes = useMemo(() => buildMenuRoutes(session?.menus ?? []), [session]);

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <>
      <div className="app-bg" aria-hidden="true" />
      <ProLayout
        title={PRODUCT_NAME}
        logo={<span className="app-logo-badge">多</span>}
        layout="side"
        navTheme={isDark ? 'realDark' : 'light'}
        fixedHeader
        fixSiderbar
        location={{ pathname: location.pathname }}
        route={{ path: '/', routes: menuRoutes }}
        token={{ sider: { colorMenuBackground: 'transparent' } }}
        menuItemRender={(item, dom) => (
          <a
            onClick={(e) => {
              e.preventDefault();
              if (item.path) navigate(item.path);
            }}
          >
            {dom}
          </a>
        )}
        onCollapse={setCollapsed}
        collapsed={collapsed}
      >
        <AppStatusBar user={user} onLogout={handleLogout} />
        <div className="app-content">
          <Outlet />
        </div>
      </ProLayout>
    </>
  );
}
