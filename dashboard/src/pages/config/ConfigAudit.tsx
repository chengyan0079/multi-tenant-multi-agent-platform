import { useCallback, useEffect, useRef, useState } from 'react';
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
  Result,
} from 'antd';
import { ProTable, type ProColumns } from '../../components/ProTable';
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
import { hasScope } from '../../services/auth';
import ReactDiffViewer from 'react-diff-viewer-continued';
import { renderCodeLine } from '../../components/CodeEditor';

const TIME_FMT = 'YYYY-MM-DD HH:mm:ss';
const STATUS_COLOR: Record<number, string> = { 0: 'orange', 1: 'blue', 2: 'red', 3: 'green', 4: 'default' };

/** 时间列统一格式化：空值或无法解析的日期显示 '-'，避免出现 'Invalid Date'。 */
const fmtTime = (v: string | null | undefined): string => {
  if (!v) return '-';
  const d = dayjs(v);
  return d.isValid() ? d.format(TIME_FMT) : '-';
};

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

  // 配置审核权限点（与后端 Scope 对齐）：列表/详情按 page/view 拦，审批动作按 execute 拦
  const canPage = hasScope('config:page');
  const canView = hasScope('config:view');
  const canExecute = hasScope('config:execute');

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

  /** 审核队列：待审核审批单 id 数组（按申请时间升序）。点「去处理」出队一份弹审核窗，主列表展示不动。 */
  const [reviewQueue, setReviewQueue] = useState<number[]>([]);
  const queueRef = useRef<number[]>([]); // 同步最新队列，供出队时读取，避免 setState updater 副作用

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
    if (!hasScope('config:page')) return;
    try {
      const res = await listGroups();
      setGroups(res?.groups ?? []);
    } catch {
      setGroups([]);
    }
  }, []);

  /** 重建审核队列：分页拉全量待审核（status=0）按申请时间升序入队，与主列表展示解耦。
   * 后端 page_size 上限 100，故按页累加（待审核通常不会很多，循环次数有限）。 */
  const rebuildQueue = useCallback(async () => {
    if (!hasScope('config:page')) return;
    try {
      const collected: { id: number; create_at: string | null }[] = [];
      const PAGE = 100;
      let page = 1;
      while (true) {
        const res = await listRequests({ status: 0, page, page_size: PAGE });
        const items = res?.items ?? [];
        for (const it of items) {
          if (it.status === 0) collected.push({ id: it.id, create_at: it.create_at });
        }
        const total = res?.total ?? 0;
        if (items.length < PAGE || page * PAGE >= total) break;
        page += 1;
      }
      collected.sort((a, b) => (dayjs(a.create_at).valueOf() || 0) - (dayjs(b.create_at).valueOf() || 0));
      setReviewQueue(collected.map((x) => x.id));
    } catch {
      setReviewQueue([]);
    }
  }, []);

  const loadRequests = useCallback(async () => {
    if (!hasScope('config:page')) return;
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

  // 页面挂载时构建一次审核队列（独立于主列表展示，筛选/分页不会重置队列进度）
  useEffect(() => {
    void rebuildQueue();
  }, [rebuildQueue]);

  useEffect(() => {
    queueRef.current = reviewQueue;
  }, [reviewQueue]);

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

  /** 出队：从审核队列头部取一份弹出审核窗，主列表展示不动。 */
  const handleProcess = useCallback(() => {
    const q = queueRef.current;
    if (q.length === 0) {
      message.info('当前没有待审核申请');
      return;
    }
    const [id, ...rest] = q;
    setReviewQueue(rest);
    setDetailId(id);
    setDetail(null);
    setComment('');
    void loadDetail(id);
    void loadReviews(id);
  }, [loadDetail, loadReviews, message]);

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
      setDetailId(null);
      setDetail(null);
      setComment('');
      void rebuildQueue(); // 刷新队列（该单已出待审核）
      void loadRequests(); // 刷新审核列表
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
      render: fmtTime,
    },
    {
      title: '生效时间',
      dataIndex: 'effective_at',
      key: 'effective_at',
      width: 170,
      render: fmtTime,
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_: unknown, row: ConfigRequestItem) => (
        canView && (
          <Button type="link" size="small" onClick={() => openDetail(row.id)}>详情</Button>
        )
      ),
    },
  ];

  if (!canPage) {
    return <Result status="403" title="无权限" subTitle="你没有查看配置审核的权限" />;
  }

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

      {reviewQueue.length > 0 && (
        <Alert
          className="audit-pending-banner"
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={
            <span>
              审核队列还有 <b className="audit-pending-num">{reviewQueue.length}</b> 条待处理（按申请时间排序），点「去处理」逐一审核
            </span>
          }
          action={
            <Button
            size="small"
            type="primary"
            disabled={!canExecute}
            onClick={handleProcess}
            >
            去处理（{reviewQueue.length}）
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
                <b style={{ marginLeft: 16 }}>提交时间：</b>{fmtTime(detail.create_at)}
                <b style={{ marginLeft: 16 }}>生效时间：</b>{fmtTime(detail.effective_at)}
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
                renderContent={(source) => renderCodeLine(source, detail.content_format ?? undefined)}
                useDarkTheme
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
                    { title: '时间', dataIndex: 'create_at', key: 'create_at', width: 200, render: fmtTime },
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
                    {canExecute && (
                      <Popconfirm title="确认审批通过并写入 Nacos？" onConfirm={() => void doReview(REVIEW_APPROVE)} okText="确认" cancelText="取消">
                        <Button type="primary" loading={acting}>审批通过</Button>
                      </Popconfirm>
                    )}
                    {canExecute && (
                      <Popconfirm title="确认驳回？" onConfirm={() => void doReview(REVIEW_REJECT)} okText="确认" cancelText="取消">
                        <Button danger loading={acting}>驳回</Button>
                      </Popconfirm>
                    )}
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
