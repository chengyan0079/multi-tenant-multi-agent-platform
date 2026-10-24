/** 各列表页面的 Mock 数据 */

export interface AgentItem {
  key: string;
  name: string;
  type: string;
  status: string;
  calls: number;
  success: number;
  updatedAt: string;
}

export const agents: AgentItem[] = [
  { key: '1', name: 'qa-agent', type: '问答', status: '运行中', calls: 4820, success: 99.4, updatedAt: '2026-10-24 10:30' },
  { key: '2', name: 'resume-agent', type: '简历审查', status: '运行中', calls: 2610, success: 98.7, updatedAt: '2026-10-24 10:12' },
  { key: '3', name: 'interview-agent', type: '模拟面试', status: '运行中', calls: 1980, success: 99.1, updatedAt: '2026-10-24 09:50' },
  { key: '4', name: 'exam-agent', type: '试卷批改', status: '维护中', calls: 1740, success: 97.2, updatedAt: '2026-10-23 18:22' },
  { key: '5', name: 'knowledge-agent', type: '知识库', status: '运行中', calls: 1714, success: 99.6, updatedAt: '2026-10-24 10:05' },
];

export interface SessionItem {
  key: string;
  threadId: string;
  user: string;
  tenant: string;
  agent: string;
  status: string;
  messages: number;
  createdAt: string;
}

export const sessions: SessionItem[] = [
  { key: '1', threadId: 'th-7a1f', user: '1001', tenant: '100', agent: 'qa-agent', status: '进行中', messages: 12, createdAt: '2026-10-24 10:20' },
  { key: '2', threadId: 'th-9f2c', user: '1001', tenant: '200', agent: 'resume-agent', status: '转人工', messages: 8, createdAt: '2026-10-24 10:15' },
  { key: '3', threadId: 'th-3b8d', user: '2001', tenant: '300', agent: 'interview-agent', status: '已完成', messages: 24, createdAt: '2026-10-24 09:40' },
  { key: '4', threadId: 'th-5e6a', user: '3001', tenant: '100', agent: 'exam-agent', status: '已完成', messages: 6, createdAt: '2026-10-24 09:12' },
  { key: '5', threadId: 'th-2c4e', user: '1001', tenant: '100', agent: 'knowledge-agent', status: '失败', messages: 3, createdAt: '2026-10-24 08:55' },
];

export interface ToolItem {
  key: string;
  name: string;
  plugin: string;
  type: string;
  enabled: boolean;
  calls: number;
}

export const tools: ToolItem[] = [
  { key: '1', name: 'web_search', plugin: 'search-plugin', type: '检索', enabled: true, calls: 5210 },
  { key: '2', name: 'resume_parser', plugin: 'hr-plugin', type: '解析', enabled: true, calls: 2610 },
  { key: '3', name: 'exam_grader', plugin: 'edu-plugin', type: '批改', enabled: false, calls: 1740 },
  { key: '4', name: 'vector_search', plugin: 'rag-plugin', type: '检索', enabled: true, calls: 3980 },
];

export interface RbacItem {
  key: string;
  userId: string;
  userName: string;
  tenantId: string;
  tenantName: string;
  role: string;
}

export const rbacBindings: RbacItem[] = [
  { key: '1', userId: '1001', userName: 'dev-user', tenantId: '100', tenantName: 'default-tenant', role: 'student' },
  { key: '2', userId: '1001', userName: 'dev-user', tenantId: '200', tenantName: 'school-a', role: 'admin' },
  { key: '3', userId: '1001', userName: 'dev-user', tenantId: '300', tenantName: 'school-b', role: 'teacher' },
  { key: '4', userId: '2001', userName: 'teacher-test', tenantId: '200', tenantName: 'school-a', role: 'teacher' },
  { key: '5', userId: '3001', userName: 'admin-test', tenantId: '300', tenantName: 'school-b', role: 'teacher' },
];

export interface RoleItem {
  key: string;
  roleId: number;
  name: string;
  description: string;
  scopes: string;
}

export const roles: RoleItem[] = [
  { key: '1', roleId: 1, name: 'student', description: '学员角色', scopes: 'qa:ask, qa:read, interview:ask, exam:read, ...' },
  { key: '2', roleId: 2, name: 'teacher', description: '教师角色', scopes: 'exam:create, exam:update, knowledge:upload, ...' },
  { key: '3', roleId: 3, name: 'admin', description: '平台管理员', scopes: '*' },
  { key: '5', roleId: 5, name: 'tenant_admin', description: '租户管理员', scopes: 'qa:read, audit:read, rbac:read, rbac:write' },
];

export interface ConfigItem {
  key: string;
  namespace: string;
  group: string;
  dataId: string;
  env: string;
  status: string;
  updatedAt: string;
}

export const configs: ConfigItem[] = [
  { key: '1', namespace: 'agent-platform', group: 'DEFAULT_GROUP', dataId: 'qa.prompt.template', env: 'dev', status: '已发布', updatedAt: '2026-10-24 10:32' },
  { key: '2', namespace: 'agent-platform', group: 'DEFAULT_GROUP', dataId: 'model.routing', env: 'dev', status: '待审核', updatedAt: '2026-10-24 10:10' },
  { key: '3', namespace: 'agent-platform', group: 'RUNTIME', dataId: 'rag.top_k', env: 'prod', status: '已发布', updatedAt: '2026-10-23 17:40' },
];

export interface AuditItem {
  key: string;
  time: string;
  user: string;
  action: string;
  resource: string;
  result: string;
  traceId: string;
}

export const auditLogs: AuditItem[] = [
  { key: '1', time: '2026-10-24 10:32:11', user: 'admin', action: '配置变更', resource: 'qa.prompt.template', result: '成功', traceId: 'tr-8a1b' },
  { key: '2', time: '2026-10-24 10:15:47', user: 'system', action: '人工转接', resource: 'thread-9f2c1a', result: '待处理', traceId: 'tr-2f9c' },
  { key: '3', time: '2026-10-24 09:41:09', user: 'system', action: '工具调用', resource: 'resume_parser', result: '失败', traceId: 'tr-6d3e' },
  { key: '4', time: '2026-10-24 09:12:33', user: 'admin', action: '角色分配', resource: 'user=1001,tenant=200', result: '成功', traceId: 'tr-1c7a' },
];
