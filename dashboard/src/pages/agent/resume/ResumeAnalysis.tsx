import { useEffect, useRef, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Card,
  Modal,
  Popconfirm,
  Result,
  Tag,
  Typography,
  Upload,
} from 'antd';
import type { UploadProps } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { ProTable, type ActionType, type ProColumns } from '../../../components/ProTable';
import { useNavigate } from 'react-router-dom';

import {
  deleteReview,
  listResumes,
  uploadResume,
  type ResumeItem,
} from '../../../services/resume';
import { hasScope } from '../../../services/auth';

type UploadFile = NonNullable<UploadProps['fileList']>[number];

const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  processing: 'processing',
  done: 'success',
  failed: 'error',
};
const STATUS_LABEL: Record<string, string> = {
  pending: '待处理',
  processing: '处理中',
  done: '已完成',
  failed: '失败',
};

const formatTime = (value: string | null): string =>
  value ? value.replace('T', ' ').slice(0, 19) : '-';

/** 简历分析：列表 + 上传 PDF，处理中自动刷新，完成后进入报告页。 */
export default function ResumeAnalysis() {
  const { message } = AntdApp.useApp();
  const navigate = useNavigate();
  const actionRef = useRef<ActionType>();

  const [uploadOpen, setUploadOpen] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [hasProcessing, setHasProcessing] = useState(false);

  const canPage = hasScope('resume:page');
  const canUpload = hasScope('resume:upload');
  const canView = hasScope('resume:view');
  const canDelete = hasScope('resume:delete');

  useEffect(() => {
    if (!hasProcessing) return undefined;
    const timer = window.setInterval(() => actionRef.current?.reload(), 3000);
    return () => window.clearInterval(timer);
  }, [hasProcessing]);

  const openUpload = () => {
    setFileList([]);
    setUploadOpen(true);
  };

  const submitUpload = async () => {
    const raw = fileList[0]?.originFileObj ?? fileList[0];
    if (!raw) {
      message.warning('请先选择简历文件');
      return;
    }
    if (!raw.name.toLowerCase().endsWith('.pdf')) {
      message.error('仅支持 PDF 文件');
      return;
    }
    setUploading(true);
    try {
      const res = await uploadResume(raw as File);
      message.success(res.message || '简历已提交，正在后台评审');
      setUploadOpen(false);
      setFileList([]);
      actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : '上传失败');
    } finally {
      setUploading(false);
    }
  };

  const onDelete = async (reviewId: string) => {
    try {
      await deleteReview(reviewId);
      message.success('评审记录已删除');
      actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : '删除失败');
    }
  };

  const columns: ProColumns<ResumeItem>[] = [
    { title: '评审ID', dataIndex: 'review_id', width: 260, ellipsis: true, copyable: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_, row) => (
        <Tag color={STATUS_COLOR[row.status] ?? 'default'}>
          {STATUS_LABEL[row.status] ?? row.status}
        </Tag>
      ),
    },
    {
      title: '综合得分',
      dataIndex: 'weighted_score',
      width: 110,
      render: (_, row) =>
        row.weighted_score == null ? (
          '-'
        ) : (
          <Typography.Text strong>{row.weighted_score.toFixed(1)}</Typography.Text>
        ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (_, row) => formatTime(row.created_at),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 170,
      render: (_, row) => formatTime(row.updated_at),
    },
    {
      title: '操作',
      width: 140,
      valueType: 'option',
      render: (_, row) => [
        canView && (row.status === 'done' || row.status === 'failed') ? (
          <Typography.Link
            key="report"
            onClick={() => navigate(`/agent/resume/analysis/${row.review_id}`)}
          >
            {row.status === 'failed' ? '查看' : '报告'}
          </Typography.Link>
        ) : null,
        canDelete ? (
          <Popconfirm
            key="delete"
            title="删除该评审记录？"
            onConfirm={() => void onDelete(row.review_id)}
            okText="删除"
            cancelText="取消"
          >
            <Typography.Link type="danger">删除</Typography.Link>
          </Popconfirm>
        ) : null,
      ],
    },
  ];

  if (!canPage) {
    return <Result status="403" title="无权限" subTitle="你没有查看简历分析的权限" />;
  }

  return (
    <Card
      title={<Typography.Title level={4} style={{ margin: 0 }}>简历分析</Typography.Title>}
      extra={
        <Button type="primary" disabled={!canUpload} onClick={openUpload}>
          上传简历
        </Button>
      }
    >
      <ProTable<ResumeItem>
        actionRef={actionRef}
        rowKey="review_id"
        search={false}
        options={{ reload: true }}
        columns={columns}
        request={async (params) => {
          try {
            const res = await listResumes({
              page: params.current ?? 1,
              page_size: params.pageSize ?? 20,
            });
            setHasProcessing(
              res.items.some((i) => i.status === 'processing' || i.status === 'pending'),
            );
            return { data: res.items, total: res.total, success: true };
          } catch (e) {
            message.error(e instanceof Error ? e.message : '简历列表加载失败');
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        scroll={{ x: 'max-content' }}
      />

      <Modal
        title="上传简历"
        open={uploadOpen}
        onCancel={() => setUploadOpen(false)}
        onOk={() => void submitUpload()}
        okText="上传并分析"
        cancelText="取消"
        confirmLoading={uploading}
        destroyOnClose
      >
        <Upload.Dragger
          beforeUpload={(file) => {
            if (!file.name.toLowerCase().endsWith('.pdf')) {
              message.error('仅支持 PDF 文件');
              return Upload.LIST_IGNORE;
            }
            return false;
          }}
          maxCount={1}
          fileList={fileList}
          onChange={({ fileList: fl }) => setFileList(fl)}
          accept=".pdf"
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽简历 PDF 到此处</p>
          <p className="ant-upload-hint">仅支持 PDF；上传后后台异步评审，列表会自动刷新</p>
        </Upload.Dragger>
      </Modal>
    </Card>
  );
}
