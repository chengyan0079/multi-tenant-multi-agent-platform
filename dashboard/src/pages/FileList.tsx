import { useCallback, useEffect, useState, type Key } from 'react';
import {
  Alert,
  App as AntdApp,
  Button,
  Descriptions,
  Divider,
  Drawer,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd';
import { ProTable, type ProColumns } from '@ant-design/pro-components';
import { DownloadOutlined, InboxOutlined, UploadOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd/es/upload/interface';
import dayjs from 'dayjs';

import {
  downloadFile,
  getFile,
  getFileConfig,
  listFiles,
  parseFiles,
  uploadFile,
  type FileDetail,
  type FileItem,
} from '../services/files';

const { Dragger } = Upload;

/** 文件大小人性化显示。 */
function formatSize(bytes: number): string {
  if (!bytes || bytes < 0) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

const PARSE_STATUS_META: Record<string, { text: string; color: string }> = {
  pending: { text: '未解析', color: 'default' },
  parsing: { text: '解析中', color: 'processing' },
  parsed: { text: '已解析', color: 'success' },
  failed: { text: '解析失败', color: 'error' },
};

export default function FileList() {
  const { message } = AntdApp.useApp();
  const [data, setData] = useState<FileItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keywordInput, setKeywordInput] = useState('');
  const [query, setQuery] = useState('');
  const [selectedRowKeys, setSelectedRowKeys] = useState<Key[]>([]);

  const [drawerFile, setDrawerFile] = useState<FileDetail | null>(null);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [remark, setRemark] = useState('');
  const [uploading, setUploading] = useState(false);
  const [maxUploadMb, setMaxUploadMb] = useState(200);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listFiles({
        page,
        page_size: pageSize,
        file_name: query || undefined,
      });
      setData(res.items);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, query]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    getFileConfig()
      .then((r) => setMaxUploadMb(r.max_upload_mb))
      .catch(() => {
        /* 读取失败沿用默认值 */
      });
  }, []);

  const openDetail = async (id: number) => {
    setDrawerFile(null);
    try {
      setDrawerFile(await getFile(id));
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDownload = async (row: FileItem) => {
    try {
      await downloadFile(row.id, row.file_name);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const doUpload = async () => {
    const f = fileList[0]?.originFileObj as File | undefined;
    if (!f) {
      message.warning('请先选择文件');
      return;
    }
    if (!/\.(pdf|md|txt)$/i.test(f.name)) {
      message.warning('仅支持上传 PDF / Markdown / TXT 文件');
      return;
    }
    if (f.size > maxUploadMb * 1024 * 1024) {
      message.warning(`文件超过 ${maxUploadMb}MB 上限`);
      return;
    }
    setUploading(true);
    try {
      await uploadFile(f, remark.trim() || undefined);
      message.success('上传成功');
      setUploadOpen(false);
      setFileList([]);
      setRemark('');
      if (page === 1) {
        void load();
      } else {
        setPage(1);
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  };

  const columns: ProColumns<FileItem>[] = [
    { title: '文件名', dataIndex: 'original_name', key: 'original_name', ellipsis: true },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 110,
      render: (_, record) => formatSize(record.file_size),
    },
    {
      title: '类型',
      dataIndex: 'content_type',
      key: 'content_type',
      width: 170,
      ellipsis: true,
      render: (_, record) => record.content_type ?? record.file_ext ?? '-',
    },
    {
      title: '版本',
      dataIndex: 'file_version',
      key: 'file_version',
      width: 90,
      render: (_, record) => (
        <Tag color="blue">
          v{record.file_version}
          {record.version_count && record.version_count > 1 ? `（共 ${record.version_count} 版）` : ''}
        </Tag>
      ),
    },
    {
      title: '解析状态',
      dataIndex: 'parse_status',
      key: 'parse_status',
      width: 110,
      render: (_, record) => {
        const meta =
          PARSE_STATUS_META[record.parse_status ?? 'pending'] ?? PARSE_STATUS_META.pending;
        return <Tag color={meta.color}>{meta.text}</Tag>;
      },
    },
    {
      title: '租户',
      dataIndex: 'tenant_id',
      key: 'tenant_id',
      width: 90,
      render: (_, record) => record.tenant_id ?? '-',
    },
    { title: '上传用户', dataIndex: 'uploader_user_id', key: 'uploader_user_id', width: 110 },
    {
      title: '上传时间',
      dataIndex: 'create_at',
      key: 'create_at',
      width: 170,
      render: (_, record) =>
        record.create_at ? dayjs(record.create_at).format('YYYY-MM-DD HH:mm:ss') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_, record) => (
        <Space>
          <Button type="link" onClick={() => openDetail(record.id)}>
            详情
          </Button>
          <Button
            type="link"
            icon={<DownloadOutlined />}
            onClick={() => handleDownload(record)}
          >
            下载
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        文件列表
      </Typography.Title>
      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          placeholder="按文件名搜索"
          value={keywordInput}
          onChange={(e) => setKeywordInput(e.target.value)}
          onPressEnter={() => {
            setQuery(keywordInput.trim());
            setPage(1);
          }}
          style={{ width: 240 }}
          allowClear
        />
        <Button
          type="primary"
          onClick={() => {
            setQuery(keywordInput.trim());
            setPage(1);
          }}
        >
          查询
        </Button>
        <Button onClick={() => void load()}>刷新</Button>
        <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>
          上传文件
        </Button>
        <Popconfirm
          title="确认解析选中的文件？"
          description={`将提交 ${selectedRowKeys.length} 个文件到消息队列进行向量化解析`}
          okText="确认解析"
          cancelText="取消"
          disabled={selectedRowKeys.length === 0}
          onConfirm={async () => {
            try {
              const ids = selectedRowKeys.map((k) => Number(k));
              await parseFiles(ids);
              message.success(`已提交 ${ids.length} 个文件解析`);
              setSelectedRowKeys([]);
              void load();
            } catch (e) {
              message.error(e instanceof Error ? e.message : String(e));
            }
          }}
        >
          <Button disabled={selectedRowKeys.length === 0}>
            解析{selectedRowKeys.length > 0 ? `（${selectedRowKeys.length}）` : ''}
          </Button>
        </Popconfirm>
        <Typography.Text type="secondary">共 {total} 个文件</Typography.Text>
      </Space>

      {error && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={`加载失败：${error}`}
          action={
            <Button size="small" onClick={() => void load()}>
              重试
            </Button>
          }
        />
      )}

      <ProTable<FileItem>
        search={false}
        options={{ fullScreen: true, setting: true, density: true, reload: false }}
        rowKey="id"
        rowSelection={{ selectedRowKeys, onChange: (keys) => setSelectedRowKeys(keys) }}
        loading={loading}
        columns={columns}
        dataSource={data}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
        scroll={{ x: 'max-content' }}
      />

      <Modal
        title="上传文件"
        open={uploadOpen}
        onCancel={() => {
          setUploadOpen(false);
          setFileList([]);
          setRemark('');
        }}
        destroyOnClose
        footer={[
          <Button
            key="cancel"
            onClick={() => {
              setUploadOpen(false);
              setFileList([]);
              setRemark('');
            }}
          >
            取消
          </Button>,
          <Popconfirm
            key="ok"
            title="确认上传该文件？"
            description="上传后将可提交向量化解析任务，是否继续？"
            okText="确认上传"
            cancelText="取消"
            disabled={fileList.length === 0}
            onConfirm={doUpload}
          >
            <Button type="primary" loading={uploading} disabled={fileList.length === 0}>
              上传
            </Button>
          </Popconfirm>,
        ]}
      >
        <Dragger
          accept=".pdf,.md,.txt"
          beforeUpload={() => false}
          maxCount={1}
          fileList={fileList}
          onChange={({ fileList: fl }) => setFileList(fl)}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽文件到此区域</p>
          <p className="ant-upload-hint">
          仅支持 PDF / Markdown / TXT；单文件上限 {maxUploadMb}MB；同名文件重复上传自动递增版本号，内容与最新版完全一致则拦截
          </p>
        </Dragger>
        <Input.TextArea
          placeholder="备注（可选）"
          value={remark}
          onChange={(e) => setRemark(e.target.value)}
          rows={2}
          style={{ marginTop: 12 }}
          maxLength={512}
        />
      </Modal>

      <Drawer
        title={`文件详情 #${drawerFile?.id ?? ''}`}
        open={drawerFile !== null}
        onClose={() => setDrawerFile(null)}
        width={560}
      >
        {drawerFile && (
          <>
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="ID">{drawerFile.id}</Descriptions.Item>
            <Descriptions.Item label="文件名">{drawerFile.file_name}</Descriptions.Item>
            <Descriptions.Item label="大小">{formatSize(drawerFile.file_size)}</Descriptions.Item>
            <Descriptions.Item label="类型">
              {drawerFile.content_type ?? drawerFile.file_ext ?? '-'}
            </Descriptions.Item>
            <Descriptions.Item label="版本">v{drawerFile.file_version}</Descriptions.Item>
            <Descriptions.Item label="租户">{drawerFile.tenant_id ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="上传用户">{drawerFile.uploader_user_id}</Descriptions.Item>
            <Descriptions.Item label="校验值">
              <code style={{ wordBreak: 'break-all' }}>{drawerFile.checksum ?? '-'}</code>
            </Descriptions.Item>
            <Descriptions.Item label="备注">{drawerFile.remark ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="上传时间">
              {dayjs(drawerFile.create_at).format('YYYY-MM-DD HH:mm:ss')}
            </Descriptions.Item>
            <Descriptions.Item label="更新时间">
              {dayjs(drawerFile.updated_at).format('YYYY-MM-DD HH:mm:ss')}
            </Descriptions.Item>
          </Descriptions>

          <Divider>版本历史</Divider>
          <Table<FileItem>
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={drawerFile.versions ?? []}
            columns={[
              {
                title: '版本',
                dataIndex: 'file_version',
                width: 90,
                render: (_, r) => (
                  <Tag color={r.id === drawerFile.id ? 'blue' : 'default'}>
                    v{r.file_version}{r.id === drawerFile.id ? '（当前）' : ''}
                  </Tag>
                ),
              },
              {
                title: '大小',
                dataIndex: 'file_size',
                width: 110,
                render: (_, r) => formatSize(r.file_size),
              },
              { title: '上传用户', dataIndex: 'uploader_user_id', width: 110 },
              {
                title: '上传时间',
                dataIndex: 'create_at',
                render: (_, r) =>
                  r.create_at ? dayjs(r.create_at).format('YYYY-MM-DD HH:mm:ss') : '-',
              },
            ]}
          />
          </>
        )}
      </Drawer>
    </div>
  );
}
