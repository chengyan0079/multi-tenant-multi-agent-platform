import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App as AntdApp,
  Button,
  Divider,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { ProTable, type ProColumns } from '@ant-design/pro-components';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import {
  approveRequest,
  rejectRequest,
  getReviews,
  getRequestDetail,
  listRequests,
  listGroups,
  REVIEW_APPROVE,
  REVIEW_REJECT,
  REQUEST_STATUS,
  OP_TYPE,
  type ConfigRequestItem,
  type ConfigRequestDetail,
  type ConfigReviewItem,
} from '../../services/configCenter';
import ReactDiffViewer from 'react-diff-viewer-continued';

const TIME_FMT = 'YYYY-MM-DD HH:mm:ss';
const STATUS_COLOR: Record<number, string> = { 0: 'orange', 1: 'blue', 2: 'red', 3: 'green', 4: 'default' };

/** 列表排序：待审核（status=0）置顶，其余按申请时间倒序（最新在前）。 */
const sortRequests = (rows: ConfigRequestItem[]) =>
  [...rows].sort((a, b) => {
    const aPending = a.status === 0 ? 0 : 1;
    const bPending = b.status === 0 ? 0 : 1;
    if (aPending !== bPending) return aPending - bPending; // 待审核优先
    return (b.create_at ?? '').localeCompare(a.create_at ?? ''); // 最新在前
  });

export default function ConfigAudit() {
  const { message } = AntdApp.useApp();

  /* ============ 申请单列表（审批流） ============ */
  const [items, setItems] = useState<ConfigRequestItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [status, setStatus] = useState<number | undefined>(undefined);
  const [groupFilter, setGroupFilter] = useState<string | undefined>(undefined);
  const [groups, setGroups] = useState<string[]>([]);

  const [detailId, setDetailId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ConfigRequestDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [comment, setComment] = useState('');
  const [acting, setActing] = useState(false);

  const [reviews, setReviews] = useState<ConfigReviewItem[]>([]);
  const [reviewsLoading, setReviewsLoading] = useState(false);

  /** 当前结果里“待审核”的数量，用于在列表上方高亮提醒（默认已展示全部状态）。 */
  const pendingCount = items.filter((r) => r.status === 0).length;

  const loadReviews = useCallback(async (id: number) => {
    setReviewsLoading(true);
    try {
      const d = await getReviews(id);
      setReviews(d?.items ?? []);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
      setReviews([]);
    } finally {
      setReviewsLoading(false);
    }
  }, [message]);

  const loadGroups = useCallback(async () => {
    try {
      const res = await listGroups();
      setGroups(res?.groups ?? []);
    } catch {
      setGroups([]);
    }
  }, []);

  const loadRequests = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listRequests({ page, page_size: pageSize, status, group_id: groupFilter });
      setItems(sortRequests(res?.items ?? []));
      setTotal(res?.total ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, status, groupFilter]);

  useEffect(() => {
    void loadGroups();
  }, [loadGroups]);

  useEffect(() => {
    void loadRequests();
  }, [loadRequests]);

  const loadDetail = useCallback(async (id: number) => {
    setDetailLoading(true);
    try {
      const d = await getRequestDetail(id);
      setDetail(d);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, [message]);

  const openDetail = (id: number) => {
    setDetailId(id);
    setDetail(null);
    setComment('');
    void loadDetail(id);
    void loadReviews(id);
  };

  const doReview = async (action: number) => {
    if (detailId === null) return;
    if (action === REVIEW_REJECT && !comment.trim()) {
      message.warning('驳回请填写意见');
      return;
    }
    setActing(true);
    try {
      if (action === REVIEW_APPROVE) {
        await approveRequest(detailId, comment.trim() || undefined);
      } else {
        await rejectRequest(detailId, comment.trim() || undefined);
      }
      message.success(action === REVIEW_APPROVE ? '已审批并写入 Nacos' : '已驳回');
      await loadDetail(detailId);
      await loadRequests();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setActing(false);
    }
  };

  const reqColumns: ColumnsType<ConfigRequestItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 70 },
    { title: 'Data ID', dataIndex: 'data_id', key: 'data_id', ellipsis: true },
    { title: 'Group', dataIndex: 'group_id', key: 'group_id', width: 160, ellipsis: true },
    {
      title: '操作',
      dataIndex: 'op_type',
      key: 'op_type',
      width: 90,
      render: (v: number) => <Tag>{OP_TYPE[v] ?? v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: number) => <Tag color={STATUS_COLOR[v] ?? 'default'}>{REQUEST_STATUS[v] ?? v}</Tag>,
    },
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true, render: (v: string | null) => v ?? '-' },
    {
      title: '申请人',
      dataIndex: 'applicant_user_id',
      key: 'applicant_user_id',
      width: 120,
      render: (_: unknown, row: ConfigRequestItem) => row.applicant_name ?? row.applicant_user_id ?? '-',
    },
    {
      title: '申请时间',
      dataIndex: 'create_at',
      key: 'create_at',
      width: 170,
      render: (v: string | null) => (v ? dayjs(v).format(TIME_FMT) : '-'),
    },
    {
      title: '生效时间',
      dataIndex: 'effective_at',
      key: 'effective_at',
      width: 170,
      render: (v: string | null) => (v ? dayjs(v).format(TIME_FMT) : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_: unknown, row: ConfigRequestItem) => (
        <Button type="link" size="small" onClick={() => openDetail(row.id)}>详情</Button>
      ),
    },
  ];

  return (
    <div>
      {/* 页面标题栏 */}
      <div className="page-head">
        <Typography.Title level={4} style={{ margin: 0 }}>配置审核</Typography.Title>
      </div>

      {/* 筛选卡片 */}
      <div className="filter-card">
        <Space wrap>
          <Select
            placeholder="按状态筛选"
            value={status}
            onChange={(v) => { setStatus(v); setPage(1); }}
            allowClear
            style={{ width: 160 }}
            options={Object.entries(REQUEST_STATUS).map(([value, label]) => ({ value: Number(value), label }))}
          />
          <Select
            placeholder="按 Group 筛选"
            value={groupFilter}
            onChange={(v) => { setGroupFilter(v); setPage(1); }}
            allowClear
            style={{ width: 200 }}
            options={groups.map((g) => ({ value: g, label: g }))}
          />
          <Button type="primary" onClick={() => { setPage(1); void loadRequests(); }}>查询</Button>
          <Button onClick={() => { setStatus(undefined); setGroupFilter(undefined); setPage(1); void loadRequests(); }}>重置</Button>
        </Space>
      </div>

      {error && (
        <Alert type="error" showIcon style={{ marginBottom: 16 }} message={`加载失败：${error}`}
          action={<Button size="small" onClick={() => void loadRequests()}>重试</Button>} />
      )}

      {pendingCount > 0 && (
        <Alert
          className="audit-pending-banner"
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={
            <span>
              当前有 <b className="audit-pending-num">{pendingCount}</b> 条<b>待审核</b>申请，请尽快复核
            </span>
          }
          action={
            <Button
              size="small"
              type="primary"
              onClick={() => { setStatus(0); setPage(1); }}
            >
              去处理
            </Button>
          }
        />
      )}

      <ProTable<ConfigRequestItem>
        search={false}
        options={{ fullScreen: true, setting: true, density: true, reload: false }}
        rowKey="id"
        columns={reqColumns as ProColumns<ConfigRequestItem>[]}
        dataSource={items}
        rowClassName={(row) => (row.status === 0 ? 'row-pending-audit' : '')}
        loading={loading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: page, pageSize, total,
          showSizeChanger: true,
          onChange: (p, ps) => { setPage(p); setPageSize(ps); },
        }}
      />

      {/* 申请单详情 + 对比 + 审核历史 + 复核（大窗口） */}
      <Modal
        title={`配置申请 #${detailId ?? ''}`}
        open={detailId !== null}
        onCancel={() => { setDetailId(null); setDetail(null); setComment(''); }}
        width={1080}
        style={{ top: 20 }}
        styles={{ body: { maxHeight: '74vh', overflowY: 'auto' } }}
        footer={null}
      >
        <Spin spinning={detailLoading}>
          {detail && (
            <Space direction="vertical" className="config-audit-detail" style={{ width: '100%' }} size={8}>
              <div>
                <b>状态：</b>
                <Tag color={STATUS_COLOR[detail.status] ?? 'default'}>{REQUEST_STATUS[detail.status] ?? detail.status}</Tag>
                <b style={{ marginLeft: 16 }}>操作：</b>
                <Tag>{OP_TYPE[detail.op_type] ?? detail.op_type}</Tag>
              </div>
              <div>
                <b>dataId：</b><code>{detail.data_id}</code>
                <b style={{ marginLeft: 16 }}>group：</b><code>{detail.group_id}</code>
                <b style={{ marginLeft: 16 }}>namespace：</b><code>{detail.namespace}</code>
              </div>
              <div>
                <b>申请人：</b>{detail.applicant_name ?? detail.applicant_user_id ?? '-'}
                <b style={{ marginLeft: 16 }}>复核人：</b>{detail.reviewer_name ?? detail.reviewer_user_id ?? '-'}
                <b style={{ marginLeft: 16 }}>提交时间：</b>{detail.create_at ? dayjs(detail.create_at).format(TIME_FMT) : '-'}
                <b style={{ marginLeft: 16 }}>生效时间：</b>{detail.effective_at ? dayjs(detail.effective_at).format(TIME_FMT) : '-'}
              </div>
              {detail.title ? <div><b>标题：</b>{detail.title}</div> : null}
              {detail.reason ? <div><b>申请原因：</b>{detail.reason}</div> : null}
              {detail.src_history_nid ? <div><b>回滚来源：</b>历史版本 nid={detail.src_history_nid}</div> : null}

              <Divider titlePlacement="left">内容对比（当前 vs 申请）</Divider>
              <ReactDiffViewer
                oldValue={detail.old_content ?? ''}
                newValue={detail.content_new ?? ''}
                splitView
                leftTitle="当前内容（Nacos 实时）"
                rightTitle="申请内容"
              />

              <Divider titlePlacement="left">审核历史</Divider>
              <Spin spinning={reviewsLoading}>
                <ProTable<ConfigReviewItem>
                  search={false}
                  options={{ fullScreen: true, setting: true, density: true, reload: false }}
                  rowKey="id"
                  size="small"
                  dataSource={reviews}
                  pagination={false}
                  columns={[
                    { title: '动作', dataIndex: 'action', key: 'action', width: 100, render: (v: number) => <Tag color={v === 1 ? 'green' : 'red'}>{v === 1 ? '通过' : '驳回'}</Tag> },
                    { title: '复核人', dataIndex: 'reviewer_user_id', key: 'reviewer_user_id', width: 120, render: (v: string | null, row: ConfigReviewItem) => row.reviewer_name ?? v ?? '-' },
                    { title: '意见', dataIndex: 'comment', key: 'comment', render: (v: string | null) => v ?? '-' },
                    { title: '时间', dataIndex: 'create_at', key: 'create_at', width: 200, render: (v: string | null) => (v ? dayjs(v).format(TIME_FMT) : '-') },
                  ] as ProColumns<ConfigReviewItem>[]}
                />
              </Spin>

              {detail.status === 1 && <Alert type="info" showIcon message="已通过，正在写入 Nacos" />}
              {detail.status === 2 && <Alert type="warning" showIcon message="已驳回，不可再执行" />}
              {detail.status === 3 && <Alert type="success" showIcon message="已发布：配置已写入 Nacos" />}
              {detail.status === 4 && <Alert type="info" showIcon message="已撤回" />}

              {detail.status === 0 && (
                <div style={{ marginTop: 8 }}>
                  <Input.TextArea rows={2} placeholder="复核意见（驳回必填）" value={comment}
                    onChange={(e) => setComment(e.target.value)} style={{ marginBottom: 12 }} />
                  <Space>
                    <Popconfirm title="确认审批通过并写入 Nacos？" onConfirm={() => void doReview(REVIEW_APPROVE)} okText="确认" cancelText="取消">
                      <Button type="primary" loading={acting}>审批通过</Button>
                    </Popconfirm>
                    <Popconfirm title="确认驳回？" onConfirm={() => void doReview(REVIEW_REJECT)} okText="确认" cancelText="取消">
                      <Button danger loading={acting}>驳回</Button>
                    </Popconfirm>
                  </Space>
                </div>
              )}
            </Space>
          )}
        </Spin>
      </Modal>
    </div>
  );
}
