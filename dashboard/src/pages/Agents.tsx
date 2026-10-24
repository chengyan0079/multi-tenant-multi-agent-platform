import { useEffect, useState } from 'react';
import { Alert, Card, Space, Switch, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';

import { listAgents, setAgentEnabled, type AgentItem } from '../services/agents';

export default function Agents() {
  const [items, setItems] = useState<AgentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listAgents();
      setItems(res?.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const toggle = async (agentType: string, enabled: boolean) => {
    setPending(agentType);
    try {
      await setAgentEnabled(agentType, enabled);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  };

  const columns: ColumnsType<AgentItem> = [
    { title: '智能体', dataIndex: 'name', key: 'name' },
    { title: '类型', dataIndex: 'agent_type', key: 'agent_type' },
    { title: '版本', dataIndex: 'version', key: 'version' },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      render: (value: boolean) => (
        <Tag color={value ? 'green' : 'orange'}>{value ? '运行中' : '维护中'}</Tag>
      ),
    },
    {
      title: '已注册',
      dataIndex: 'registered',
      key: 'registered',
      render: (value: boolean) => (
        <Tag color={value ? 'blue' : 'red'}>{value ? '已注册' : '仅库登记'}</Tag>
      ),
    },
    { title: '说明', dataIndex: 'description', key: 'description' },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at' },
    {
      title: '启停',
      key: 'action',
      render: (_: unknown, row: AgentItem) => (
        <Switch
          checked={row.enabled}
          loading={pending === row.agent_type}
          onChange={(checked) => void toggle(row.agent_type, checked)}
        />
      ),
    },
  ];

  return (
    <Card title={<Typography.Title level={4} style={{ margin: 0 }}>智能体管理</Typography.Title>}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        {error && <Alert type="error" showIcon message={`加载失败：${error}`} />}
        <Table<AgentItem>
          rowKey="agent_type"
          columns={columns}
          dataSource={items}
          loading={loading}
          pagination={false}
          scroll={{ x: 'max-content' }}
        />
      </Space>
    </Card>
  );
}
