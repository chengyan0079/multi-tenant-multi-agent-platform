import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Space, Tag, Typography } from 'antd';
import { ProTable, type ProColumns } from '@ant-design/pro-components';
import type { ColumnsType } from 'antd/es/table';

import { listPlugins } from '../services/plugins';

interface ToolRow {
  key: string;
  name: string;
}

export default function Tools() {
  const [rows, setRows] = useState<ToolRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listPlugins();
      const capabilities = res?.capabilities ?? [];
      setRows(capabilities.map((name) => ({ key: name, name })));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ColumnsType<ToolRow> = [
    {
      title: '工具能力',
      dataIndex: 'name',
      key: 'name',
      render: (v: string) => <code>{v}</code>,
    },
    {
      title: '状态',
      key: 'status',
      width: 160,
      render: () => <Tag color="green">已注册</Tag>,
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        工具与插件
      </Typography.Title>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="只展示后端已注册的工具能力清单"
        description="工具级启停开关、调用次数统计后端暂未提供接口，所以本页没有这两个能力。"
      />

      <Space style={{ marginBottom: 16 }}>
        <Button onClick={() => load()}>刷新</Button>
        <Typography.Text type="secondary">共 {rows.length} 个能力</Typography.Text>
      </Space>

      {error && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={`加载失败：${error}`}
          action={
            <Button size="small" onClick={() => load()}>
              重试
            </Button>
          }
        />
      )}

      <ProTable<ToolRow>
        search={false}
        options={{ fullScreen: true, setting: true, density: true, reload: false }}
        rowKey="key"
        columns={columns as ProColumns<ToolRow>[]}
        dataSource={rows}
        loading={loading}
        pagination={false}
      />
    </div>
  );
}
