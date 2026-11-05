import type { ReactNode } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import MainLayout from './layouts/MainLayout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Agents from './pages/Agents';
import Sessions from './pages/Sessions';
import Tools from './pages/Tools';
import UserList from './pages/rbac/UserList';
import TenantList from './pages/rbac/TenantList';
import RoleList from './pages/rbac/RoleList';
import MenuList from './pages/rbac/MenuList';
import ConfigList from './pages/config/ConfigList';
import ConfigAudit from './pages/config/ConfigAudit';
import AuditLog from './pages/AuditLog';
import AuditLoginLog from './pages/AuditLoginLog';
import AuditApiLog from './pages/AuditApiLog';
import AuditReviewLog from './pages/config/AuditReviewLog';
import MessageQueueList from './pages/MessageQueueList';
import DeadLetterList from './pages/DeadLetterList';
import ModelList from './pages/ModelList';
import FileList from './pages/FileList';
import ResumeUpload from './pages/resume/ResumeUpload';
import ResumeList from './pages/resume/ResumeList';
import ResumeView from './pages/resume/ResumeView';
import { hasScope, isLogin } from './services/auth';

/** 登录守卫：未登录跳转登录页 */
function RequireAuth({ children }: { children: ReactNode }) {
  if (!isLogin()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

/** 权限守卫：缺指定 scope 时跳回控制台；菜单隐藏只是入口过滤，直链仍需拦截 */
function RequireScope({ scope, children }: { scope: string; children: ReactNode }) {
  if (!hasScope(scope)) {
    return <Navigate to="/dashboard" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <MainLayout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="agents" element={<Agents />} />
        <Route path="sessions" element={<Sessions />} />
        <Route path="tools" element={<Tools />} />
        <Route path="models" element={<ModelList />} />
        <Route path="files" element={<Navigate to="/files/list" replace />} />
        <Route path="files/list" element={<FileList />} />
        <Route
          path="users"
          element={
            <RequireScope scope="user:menu">
              <UserList />
            </RequireScope>
          }
        />
        <Route
          path="tenants"
          element={
            <RequireScope scope="tenant:menu">
              <TenantList />
            </RequireScope>
          }
        />
        <Route
          path="roles"
          element={
            <RequireScope scope="role:menu">
              <RoleList />
            </RequireScope>
          }
        />
        <Route
          path="menus"
          element={
            <RequireScope scope="menu:menu">
              <MenuList />
            </RequireScope>
          }
        />
        <Route path="rbac" element={<Navigate to="/users" replace />} />
        <Route path="config" element={<Navigate to="/config/request" replace />} />
        <Route path="config/request" element={<ConfigList />} />
        <Route path="config/review" element={<ConfigAudit />} />
        <Route path="config/review-log" element={<AuditReviewLog />} />
        <Route path="audit" element={<AuditLog />} />
        <Route path="audit/operation" element={<AuditLog />} />
        <Route path="audit/login" element={<AuditLoginLog />} />
        <Route path="audit/api" element={<AuditApiLog />} />
        <Route path="messages" element={<Navigate to="/messages/queue" replace />} />
        <Route path="messages/queue" element={<MessageQueueList />} />
        <Route path="messages/dead-letters" element={<DeadLetterList />} />
        <Route path="resume" element={<Navigate to="/resume/upload" replace />} />
        <Route
          path="resume/upload"
          element={
            <RequireScope scope="resume:upload">
              <ResumeUpload />
            </RequireScope>
          }
        />
        <Route
          path="resume/page"
          element={
            <RequireScope scope="resume:page">
              <ResumeList />
            </RequireScope>
          }
        />
        <Route
          path="resume/view/:id"
          element={
            <RequireScope scope="resume:view">
              <ResumeView />
            </RequireScope>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
