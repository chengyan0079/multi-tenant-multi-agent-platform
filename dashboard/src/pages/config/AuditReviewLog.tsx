import { App as AntdApp, Tag, Typography } from 'antd';
import { ProTable, type ProColumns } from '../../components/ProTable';
import dayjs from 'dayjs';

import {
  OP_TYPE,
  REQUEST_STATUS,
  listReviewLogs,
  type ReviewLogItem,
} from '../../services/configCenter';

const TIME_FMT = 'YYYY-MM-DD HH:mm:ss';

/** 审核记录：agent_config_review 全量复核记录，只读列表（复核人/动作已由后端关联）。 */
export default function AuditReviewLog() {
  const { message } = AntdApp.useApp();

  const columns: ProColumns<ReviewLogItem>[] = [
    {
      title: '时间',
      dataIndex: 'create_at',
      key: 'create_at',
      width: 170,
      render: (v) => (v ? dayjs(v as string).format(TIME_FMT) : '-'),
    },
    { title: 'Data ID', dataIndex: 'data_id', key: 'data_id', ellipsis: true },
    { title: 'Group', dataIndex: 'group_id', key: 'group_id', width: 150, ellipsis: true },
    {
      title: '操作类型',
      dataIndex: 'op_type',
      key: 'op_type',
      width: 100,
      render: (v) => (v === null || v === undefined ? '-' : OP_TYPE[Number(v)] ?? String(v)),
    },
    { title: '审批单标题', dataIndex: 'title', key: 'title', ellipsis: true, render: (v) => v ?? '-' },
    {
      title: '审批状态',
      dataIndex: 'approval_status',
      key: 'approval_status',
      width: 100,
      render: (v) => {
        if (v === null || v === undefined) return '-';
        const status = Number(v);
        return <Tag>{REQUEST_STATUS[status] ?? String(status)}</Tag>;
      },
    },
    {
      title: '复核人',
      dataIndex: 'reviewer_user_id',
      key: 'reviewer_user_id',
      width: 120,
      render: (_v, row) => row.reviewer_name ?? row.reviewer_user_id ?? '-',
    },
    {
      title: '动作',
      dataIndex: 'action',
      key: 'action',
      width: 90,
      render: (_v, row) => (
        <Tag color={row.action === 1 ? 'green' : 'red'}>{row.action_name ?? String(row.action)}</Tag>
      ),
    },
    { title: '意见', dataIndex: 'comment', key: 'comment', render: (v) => v ?? '-' },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        审核记录
      </Typography.Title>
      <ProTable<ReviewLogItem>
        search={false}
        options={{ fullScreen: true, setting: true, density: true, reload: true }}
        rowKey="id"
        columns={columns}
        request={async (params) => {
          try {
            const res = await listReviewLogs({
              page: params.current ?? 1,
              page_size: params.pageSize ?? 20,
            });
            return {
              data: res?.items ?? [],
              total: res?.total ?? 0,
              success: true,
            };
          } catch (e) {
            message.error(e instanceof Error ? e.message : String(e));
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        scroll={{ x: 'max-content' }}
      />
    </div>
  );
}
