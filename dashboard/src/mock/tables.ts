/**
 * 列表页 Mock 数据。
 *
 * 现在只剩「会话运行」用假数据：后端没有会话分页列表接口，前端接不了。
 * 其它列表页（智能体、工具、用户、租户、角色、菜单、配置、审计、模型）都已接真实接口，
 * 相应假数据已删除，避免误当成真实数据。
 */

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
