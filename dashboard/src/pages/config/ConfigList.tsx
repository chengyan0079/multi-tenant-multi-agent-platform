import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  App as AntdApp,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tag,
} from 'antd';
import { ProTable, type ProColumns, type ActionType } from '@ant-design/pro-components';
import dayjs from 'dayjs';

import {
  addConfig,
  modifyConfig,
  deleteConfig,
  createRollback,
  getConfigDetail,
  listConfigs,
  listGroups,
  listHistory,
  getHistoryDetail,
  listRequests,
  withdrawRequest,
  type NacosConfigItem,
  type NacosHistoryItem,
  type NacosHistoryDetail,
} from '../../services/configCenter';
import ReactDiffViewer from 'react-diff-viewer-continued';
import { getSession } from '../../services/auth';

/** 后端 Nacos 客户端使用的固定命名空间（前端仅有展示意义，实际以服务端为准） */
const NACOS_NAMESPACE = 'agent-platform';
const TIME_FMT = 'YYYY-MM-DD HH:mm:ss';

/** Nacos 配置格式；列表/详情返回的 type 可能是大写或空，统一归一到小写可选项。 */
const FORMAT_OPTIONS = ['text', 'json', 'yaml', 'xml', 'properties', 'html'];

function normalizeFormat(type?: string | null): string {
  const t = (type ?? '').toLowerCase();
  return FORMAT_OPTIONS.includes(t) ? t : 'text';
}

/** 历史时间兼容 epoch 毫秒/秒与 ISO 字符串，无效值回落为原值。 */
function fmtHistoryTime(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  const raw = String(value);
  const numeric = Number(value);
  let d;
  if (Number.isFinite(numeric) && !raw.includes('-') && !raw.includes('T')) {
    // Nacos 历史时间多为 13 位毫秒；兼容 10 位秒
    const ms = raw.length >= 13 ? numeric : raw.length >= 10 ? numeric * 1000 : numeric;
    d = dayjs(ms);
  } else {
    d = dayjs(raw);
  }
  return d.isValid() ? d.format(TIME_FMT) : raw;
}

interface AddValues {
  group_id: string;
  data_id: string;
  content_format: string;
  content_new: string;
  title?: string;
  reason?: string;
}

interface ModifyValues {
  content_format: string;
  content_new: string;
  title?: string;
  reason?: string;
}

interface DeleteValues {
  title?: string;
  reason?: string;
}

export default function ConfigList() {
  const { message, modal } = AntdApp.useApp();

  /* ============ 配置列表（直读 Nacos） ============ */
  const [groups, setGroups] = useState<string[]>([]);
  const actionRef = useRef<ActionType>();
  const groupValueEnum = useMemo(() => Object.fromEntries(groups.map((g) => [g, g])), [groups]);

  /* 新增 / 修改 / 删除 三个独立窗口：可编辑字段不同，不复用同一表单 */
  const [addOpen, setAddOpen] = useState(false);
  const [modifyOpen, setModifyOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [addForm] = Form.useForm<AddValues>();
  const [modifyForm] = Form.useForm<ModifyValues>();
  const [deleteForm] = Form.useForm<DeleteValues>();
  const [modifyTarget, setModifyTarget] = useState<{ group: string; dataId: string; format: string }>({
    group: '', dataId: '', format: 'text',
  });
  const [deleteTarget, setDeleteTarget] = useState<{ group: string; dataId: string; format: string }>({
    group: '', dataId: '', format: 'text',
  });

  const [histOpen, setHistOpen] = useState(false);
  const [histItems, setHistItems] = useState<NacosHistoryItem[]>([]);
  const [histLoading, setHistLoading] = useState(false);
  const [histDataId, setHistDataId] = useState('');
  const [histGroup, setHistGroup] = useState<string | undefined>(undefined);
  const [histType, setHistType] = useState<string | undefined>(undefined);

  const [histDetailOpen, setHistDetailOpen] = useState(false);
  const [histDetailData, setHistDetailData] = useState<NacosHistoryDetail | null>(null);
  const [histDetailLoading, setHistDetailLoading] = useState(false);

  const [cfgDetailOpen, setCfgDetailOpen] = useState(false);
  const [cfgDetailContent, setCfgDetailContent] = useState<string | null>(null);
  const [cfgDetailLoading, setCfgDetailLoading] = useState(false);
  const [cfgDetailMeta, setCfgDetailMeta] = useState<{
    dataId: string; group: string; type?: string; md5?: string;
    createTime?: string | number; modifyTime?: string | number; lastModified?: string | number;
  } | null>(null);

  /* ============ 回滚预览：历史版本 vs 当前生效配置 ============ */
  const [rbOpen, setRbOpen] = useState(false);
  const [rbLoading, setRbLoading] = useState(false);
  const [rbSubmitting, setRbSubmitting] = useState(false);
  const [rbMeta, setRbMeta] = useState<{ group: string; dataId: string; nid: number } | null>(null);
  const [rbCurrent, setRbCurrent] = useState('');
  const [rbTarget, setRbTarget] = useState<NacosHistoryDetail | null>(null);
  const [rbForm] = Form.useForm<{ title?: string; reason?: string }>();

  /* ============ 本人待复核映射（用于「撤回」按钮） ============ */
  const [pendingMap, setPendingMap] = useState<Record<string, number>>({});

  const loadPending = async () => {
    const me = getSession()?.user.user_id;
    if (me === undefined) return;
    try {
      const res = await listRequests({ status: 0, page_size: 100 });
      const map: Record<string, number> = {};
      for (const r of res?.items ?? []) {
        if (r.applicant_user_id !== null && Number(r.applicant_user_id) === me) {
          map[`${r.group_id}::${r.data_id}`] = r.id;
        }
      }
      setPendingMap(map);
    } catch {
      // 撤回按钮依赖此映射；拉取失败不影响主列表展示
    }
  };

  const doWithdraw = async (requestId: number) => {
    try {
      await withdrawRequest(requestId);
      message.success('已撤回申请');
      actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  const cfgRequest = useCallback(async (params: any) => {
    const res = await listConfigs({
      group: params.groupName || undefined,
      data_id: params.dataId || undefined,
      page_no: params.current ?? 1,
      page_size: params.pageSize ?? 20,
    });
    void loadPending();
    return { data: res?.pageItems ?? [], success: true, total: res?.totalCount ?? 0 };
  }, []);

  const loadGroups = useCallback(async () => {
    try {
      const res = await listGroups();
      setGroups(res?.groups ?? []);
    } catch {
      setGroups([]);
    }
  }, []);

  useEffect(() => {
    void loadGroups();
  }, [loadGroups]);

  /* ---- 配置中心操作：新增 / 修改 / 删除各自独立 ---- */
  const openAdd = () => {
    addForm.resetFields();
    setAddOpen(true);
  };

  const openModify = (group: string, dataId: string, type?: string) => {
    setModifyTarget({ group, dataId, format: normalizeFormat(type) });
    setModifyOpen(true);
  };

  const openDelete = (group: string, dataId: string, type?: string) => {
    setDeleteTarget({ group, dataId, format: normalizeFormat(type) });
    deleteForm.resetFields();
    setDeleteOpen(true);
  };

  /** 修改窗口：打开后拉取 Nacos 当前内容回填，避免内容为空。 */
  useEffect(() => {
    if (!modifyOpen) return;
    let cancelled = false;
    (async () => {
      try {
        const d = await getConfigDetail(modifyTarget.dataId, modifyTarget.group || undefined);
        if (cancelled) return;
        modifyForm.setFieldsValue({
          content_new: d?.content ?? '',
          content_format: modifyTarget.format,
        });
      } catch (e) {
        if (!cancelled) message.error(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [modifyOpen, modifyTarget, modifyForm, message]);

  const submitAdd = async (values: AddValues) => {
    setSaving(true);
    try {
      const res = await addConfig({
        namespace: NACOS_NAMESPACE,
        group_id: values.group_id,
        data_id: values.data_id,
        content_new: values.content_new,
        content_format: values.content_format,
        title: values.title,
        reason: values.reason,
      });
      message.success(`新增申请已提交（#${res.id}），待复核`);
      setAddOpen(false);
      addForm.resetFields();
      actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const submitModify = async (values: ModifyValues) => {
    setSaving(true);
    try {
      const res = await modifyConfig({
        namespace: NACOS_NAMESPACE,
        group_id: modifyTarget.group,
        data_id: modifyTarget.dataId,
        content_new: values.content_new,
        content_format: values.content_format,
        title: values.title,
        reason: values.reason,
      });
      message.success(`修改申请已提交（#${res.id}），待复核`);
      setModifyOpen(false);
      actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const submitDelete = async (values: DeleteValues) => {
    setSaving(true);
    try {
      const res = await deleteConfig({
        namespace: NACOS_NAMESPACE,
        group_id: deleteTarget.group,
        data_id: deleteTarget.dataId,
        content_format: deleteTarget.format,
        title: values.title,
        reason: values.reason,
      });
      message.success(`删除申请已提交（#${res.id}），待复核`);
      setDeleteOpen(false);
      deleteForm.resetFields();
      actionRef.current?.reload();
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const openHistory = (group: string, dataId: string, type?: string) => {
    setHistDataId(dataId);
    setHistGroup(group);
    setHistType(type);
    setHistOpen(true);
    void loadHistory(dataId, group);
  };

  const loadHistory = async (dataId: string, group?: string) => {
    setHistLoading(true);
    try {
      const res = await listHistory(dataId, group);
      setHistItems(res?.pageItems ?? []);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
      setHistItems([]);
    } finally {
      setHistLoading(false);
    }
  };

  const openHistDetail = async (nid: number) => {
    setHistDetailOpen(true);
    setHistDetailLoading(true);
    try {
      const d = await getHistoryDetail(histDataId, nid, histGroup);
      setHistDetailData(d ?? null);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
      setHistDetailData(null);
    } finally {
      setHistDetailLoading(false);
    }
  };

  /* ---- 历史回滚：先对比当前生效配置，再二次确认提交 ---- */
  const openRollbackPreview = async (nid: number) => {
    const group = histGroup ?? '';
    const dataId = histDataId;
    setRbMeta({ group, dataId, nid });
    setRbCurrent('');
    setRbTarget(null);
    setRbOpen(true);
    setRbLoading(true);
    try {
      const [cur, target] = await Promise.all([
        getConfigDetail(dataId, group || undefined),
        getHistoryDetail(dataId, nid, group || undefined),
      ]);
      setRbCurrent(cur?.content ?? '');
      setRbTarget(target ?? null);
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setRbLoading(false);
    }
  };

  const submitRollback = async () => {
    if (!rbMeta) return;
    if (!rbTarget) { message.warning('历史版本内容未加载，无法回滚'); return; }
    const values = await rbForm.validateFields();
    modal.confirm({
      title: '确认回滚？',
      content: `将用历史版本 nid=${rbMeta.nid} 覆盖「${rbMeta.dataId}」的当前生效配置；提交后需复核通过才会写入 Nacos。`,
      okText: '确认回滚',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setRbSubmitting(true);
        try {
          const res = await createRollback({
            namespace: NACOS_NAMESPACE,
            group_id: rbMeta.group,
            data_id: rbMeta.dataId,
            src_history_nid: rbMeta.nid,
            content_format: histType,
            title: values.title,
            reason: values.reason,
          });
          message.success(`回滚申请已提交（#${res.id}），待复核`);
          setRbOpen(false);
          setHistOpen(false);
          actionRef.current?.reload();
        } catch (e) {
          message.error(e instanceof Error ? e.message : String(e));
          throw e;
        } finally {
          setRbSubmitting(false);
        }
      },
    });
  };

  const openCfgDetail = async (row: NacosConfigItem) => {
    setCfgDetailMeta({
      dataId: row.dataId, group: row.groupName, type: row.type,
      md5: row.md5, lastModified: row.lastModified,
    });
    setCfgDetailOpen(true);
    setCfgDetailLoading(true);
    try {
      const d = await getConfigDetail(row.dataId, row.groupName);
      setCfgDetailContent(d?.content ?? null);
      // 详情接口返回权威的创建/修改时间与 md5，回填覆盖列表项的预估值
      setCfgDetailMeta((prev) => ({
        dataId: prev?.dataId ?? row.dataId,
        group: prev?.group ?? row.groupName,
        type: d?.type ?? prev?.type,
        md5: d?.md5 ?? prev?.md5,
        createTime: d?.createTime ?? prev?.createTime,
        modifyTime: d?.modifyTime ?? prev?.modifyTime,
        lastModified: d?.lastModified ?? d?.modifyTime ?? prev?.lastModified,
      }));
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
      setCfgDetailContent(null);
    } finally {
      setCfgDetailLoading(false);
    }
  };

  const cfgColumns: ProColumns<NacosConfigItem>[] = [
    { title: 'Data ID', dataIndex: 'dataId', key: 'dataId', ellipsis: true, valueType: 'text' },
    {
      title: 'Group',
      dataIndex: 'groupName',
      key: 'groupName',
      width: 180,
      ellipsis: true,
      valueType: 'select',
      valueEnum: groupValueEnum,
      fieldProps: { placeholder: '全部分组', allowClear: true },
    },
    {
      title: '配置格式',
      dataIndex: 'type',
      key: 'type',
      width: 110,
      search: false,
      render: (value: any) => <Tag color="blue">{String(value ?? 'text').toUpperCase()}</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'createTime',
      key: 'createTime',
      width: 180,
      search: false,
      render: (value: any) => fmtHistoryTime(value),
    },
    {
      title: '更新时间',
      dataIndex: 'lastModified',
      key: 'lastModified',
      width: 180,
      search: false,
      render: (value: any) => fmtHistoryTime(value),
    },
    {
      title: '操作',
      key: 'action',
      width: 300,
      search: false,
      render: (_: unknown, row: NacosConfigItem) => {
        const pendingId = pendingMap[`${row.groupName}::${row.dataId}`];
        return (
          <Space size="small" wrap>
            <Button type="link" size="small" onClick={() => openModify(row.groupName, row.dataId, row.type)}>修改</Button>
            <Button type="link" size="small" danger onClick={() => openDelete(row.groupName, row.dataId, row.type)}>删除</Button>
            {pendingId !== undefined && (
              <Popconfirm title="确认撤回该申请？" description="撤回后状态变为已撤回，需重新发起" okText="撤回" cancelText="取消" onConfirm={() => void doWithdraw(pendingId)}>
                <Button type="link" size="small">撤回</Button>
              </Popconfirm>
            )}
            <Button type="link" size="small" onClick={() => void openCfgDetail(row)}>详情</Button>
            <Button type="link" size="small" onClick={() => openHistory(row.groupName, row.dataId, row.type)}>历史</Button>
          </Space>
        );
      },
    },
  ];

  return (
    <div>
      <ProTable<NacosConfigItem>
        headerTitle="配置列表"
        actionRef={actionRef}
        toolBarRender={() => [
          <Button key="add" type="primary" onClick={openAdd}>新建配置</Button>,
        ]}
        rowKey={(r) => `${r.groupName}/${r.dataId}`}
        columns={cfgColumns}
        request={cfgRequest}
        search={{ labelWidth: 'auto' }}
        options={{ fullScreen: true, setting: true, density: true, reload: true }}
        scroll={{ x: 'max-content' }}
        pagination={{ pageSize: 20, showSizeChanger: true }}
      />

      {/* 配置详情：左右字段 + 内容 */}
      <Drawer title="配置详情（Nacos 当前内容）" open={cfgDetailOpen} onClose={() => setCfgDetailOpen(false)} width={760}>
        <Spin spinning={cfgDetailLoading}>
          <Descriptions column={1} bordered size="small" styles={{ label: { width: 120 } }}>
            <Descriptions.Item label="Data ID">{cfgDetailMeta?.dataId || '-'}</Descriptions.Item>
            <Descriptions.Item label="Group">{cfgDetailMeta?.group || '-'}</Descriptions.Item>
            <Descriptions.Item label="配置格式">
              <Tag color="blue">{normalizeFormat(cfgDetailMeta?.type).toUpperCase()}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="MD5">
              {cfgDetailMeta?.md5 ? <code>{cfgDetailMeta.md5}</code> : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">{fmtHistoryTime(cfgDetailMeta?.createTime)}</Descriptions.Item>
            <Descriptions.Item label="更新时间">{fmtHistoryTime(cfgDetailMeta?.lastModified)}</Descriptions.Item>
            <Descriptions.Item label="内容">
              <pre className="config-diff" style={{ margin: 0 }}>{cfgDetailContent ?? '（无内容）'}</pre>
            </Descriptions.Item>
          </Descriptions>
        </Spin>
      </Drawer>

      {/* 历史版本（抽屉 + 详情 / 回滚） */}
      <Drawer title={`配置历史：${histDataId}`} open={histOpen} onClose={() => setHistOpen(false)} width={760}>
        <Spin spinning={histLoading}>
          <ProTable<NacosHistoryItem>
        search={false}
        options={{ fullScreen: true, setting: true, density: true, reload: false }}
            rowKey="nid"
            size="small"
            columns={[
              { title: 'nid', dataIndex: 'nid', key: 'nid', width: 90 },
              {
                title: 'md5',
                dataIndex: 'md5',
                key: 'md5',
                ellipsis: true,
                render: (v: any) => (v ? <code>{String(v)}</code> : '-'),
              },
              {
                title: '时间',
                dataIndex: 'createdTime',
                key: 'createdTime',
                width: 180,
                render: (v: any) => fmtHistoryTime(v),
              },
              {
                title: '操作', key: 'action', width: 200,
                render: (_: unknown, row: NacosHistoryItem) => (
                  <Space size="small">
                    <Button type="link" size="small" onClick={() => void openHistDetail(row.nid)}>详情</Button>
                    <Button type="link" size="small" danger onClick={() => void openRollbackPreview(row.nid)}>回滚</Button>
                  </Space>
                ),
              },
            ] as ProColumns<NacosHistoryItem>[]}
            dataSource={histItems}
            pagination={false}
          />
        </Spin>
      </Drawer>

      {/* 新建配置：group/dataId/格式/内容 均可编辑 */}
      <Modal
        title="新建配置申请"
        open={addOpen}
        onCancel={() => setAddOpen(false)}
        onOk={() => addForm.submit()}
        confirmLoading={saving}
        okText="提交新增申请"
        width={640}
        destroyOnClose
      >
        <Form form={addForm} layout="vertical" onFinish={submitAdd} initialValues={{ content_format: 'text' }}>
          <Form.Item label="namespace"><Input value={NACOS_NAMESPACE} disabled /></Form.Item>
          <Form.Item name="group_id" label="group" rules={[{ required: true }]}>
            <Input placeholder="如 DEFAULT_GROUP" />
          </Form.Item>
          <Form.Item name="data_id" label="dataId" rules={[{ required: true }]}>
            <Input placeholder="如 prompt.qa.system.json" />
          </Form.Item>
          <Form.Item name="content_format" label="内容格式" rules={[{ required: true }]}>
            <Select options={FORMAT_OPTIONS.map((f) => ({ value: f, label: f }))} />
          </Form.Item>
          <Form.Item name="content_new" label="配置内容" rules={[{ required: true, message: '请填写配置内容' }]}>
            <Input.TextArea rows={8} placeholder="粘贴完整配置内容" />
          </Form.Item>
          <Form.Item name="title" label="标题"><Input placeholder="一句话说明这次变更" /></Form.Item>
          <Form.Item name="reason" label="变更原因"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      {/* 修改配置：group/dataId 只读，格式与内容可编辑（内容回填 Nacos 当前值） */}
      <Modal
        title="修改配置申请"
        open={modifyOpen}
        onCancel={() => setModifyOpen(false)}
        onOk={() => modifyForm.submit()}
        confirmLoading={saving}
        okText="提交修改申请"
        width={640}
        destroyOnClose
      >
        <Form form={modifyForm} layout="vertical" onFinish={submitModify} preserve={false}
          initialValues={{ content_format: modifyTarget.format }}>
          <Descriptions column={1} size="small" bordered style={{ marginBottom: 12 }}>
            <Descriptions.Item label="namespace">{NACOS_NAMESPACE}</Descriptions.Item>
            <Descriptions.Item label="group">{modifyTarget.group || '-'}</Descriptions.Item>
            <Descriptions.Item label="dataId">{modifyTarget.dataId}</Descriptions.Item>
          </Descriptions>
          <Form.Item name="content_format" label="内容格式" rules={[{ required: true }]}>
            <Select options={FORMAT_OPTIONS.map((f) => ({ value: f, label: f }))} />
          </Form.Item>
          <Form.Item name="content_new" label="配置内容" rules={[{ required: true, message: '请填写配置内容' }]}>
            <Input.TextArea rows={10} placeholder="粘贴完整配置内容" />
          </Form.Item>
          <Form.Item name="title" label="标题"><Input placeholder="一句话说明这次变更" /></Form.Item>
          <Form.Item name="reason" label="变更原因"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      {/* 删除配置：只有标题与原因可编辑，其余只读 */}
      <Modal
        title="删除配置申请"
        open={deleteOpen}
        onCancel={() => setDeleteOpen(false)}
        onOk={() => deleteForm.submit()}
        confirmLoading={saving}
        okText="提交删除申请"
        okButtonProps={{ danger: true }}
        width={520}
        destroyOnClose
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="删除为高危操作，需复核通过后才会从 Nacos 移除。"
        />
        <Descriptions column={1} size="small" bordered style={{ marginBottom: 12 }}>
          <Descriptions.Item label="namespace">{NACOS_NAMESPACE}</Descriptions.Item>
          <Descriptions.Item label="group">{deleteTarget.group || '-'}</Descriptions.Item>
          <Descriptions.Item label="dataId">{deleteTarget.dataId}</Descriptions.Item>
          <Descriptions.Item label="配置格式">
            <Tag color="blue">{deleteTarget.format.toUpperCase()}</Tag>
          </Descriptions.Item>
        </Descriptions>
        <Form form={deleteForm} layout="vertical" onFinish={submitDelete}>
          <Form.Item name="title" label="标题"><Input placeholder="一句话说明这次变更" /></Form.Item>
          <Form.Item name="reason" label="变更原因"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      {/* 历史回滚：当前生效配置 vs 目标历史版本，二次确认后提交 */}
      <Modal
        title={`回滚确认：${rbMeta?.dataId ?? ''}`}
        open={rbOpen}
        onCancel={() => setRbOpen(false)}
        onOk={() => void submitRollback()}
        okText="确认回滚"
        okButtonProps={{ danger: true }}
        confirmLoading={rbSubmitting}
        width={960}
        destroyOnClose
      >
        <Spin spinning={rbLoading}>
          <Descriptions column={3} size="small" bordered style={{ marginBottom: 12 }}>
            <Descriptions.Item label="Group">{rbMeta?.group || '-'}</Descriptions.Item>
            <Descriptions.Item label="Data ID">{rbMeta?.dataId || '-'}</Descriptions.Item>
            <Descriptions.Item label="目标版本">nid={rbMeta?.nid ?? '-'}</Descriptions.Item>
          </Descriptions>
          {rbTarget ? (
            <ReactDiffViewer
              oldValue={rbCurrent}
              newValue={typeof rbTarget.content === 'string' ? rbTarget.content : ''}
              splitView
              showDiffOnly={false}
              leftTitle="当前生效配置"
              rightTitle={`历史版本 nid=${rbTarget.nid ?? rbMeta?.nid ?? '-'}`}
            />
          ) : (
            <Alert type="info" showIcon message={rbLoading ? '加载中…' : '历史版本内容不可用，无法回滚'} />
          )}
          <Form form={rbForm} layout="vertical" style={{ marginTop: 16 }}>
            <Form.Item name="title" label="标题">
              <Input placeholder={`留空则自动生成「回滚至历史 nid=${rbMeta?.nid ?? ''}」`} />
            </Form.Item>
            <Form.Item name="reason" label="回滚原因">
              <Input.TextArea rows={2} />
            </Form.Item>
          </Form>
        </Spin>
      </Modal>

      {/* 历史版本详情 */}
      <Drawer title={`历史版本详情 nid=${histDetailData?.nid ?? (histDetailData as any)?.id ?? ''}`} open={histDetailOpen} onClose={() => setHistDetailOpen(false)} width={720}>
        <Spin spinning={histDetailLoading}>
          {histDetailData ? (
            <>
              <Descriptions column={1} size="small" bordered style={{ marginBottom: 12 }} styles={{ label: { width: 90 } }}>
                <Descriptions.Item label="配置格式">
                  <Tag color="blue">{normalizeFormat((histDetailData as any).type).toUpperCase()}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="md5">
                  <code>{histDetailData.md5 == null ? '-' : String(histDetailData.md5)}</code>
                </Descriptions.Item>
                <Descriptions.Item label="时间">{fmtHistoryTime(histDetailData.createdTime ?? (histDetailData as any).lastModifiedTime)}</Descriptions.Item>
              </Descriptions>
              <pre className="config-diff">{typeof histDetailData.content === 'string' ? histDetailData.content : '（无内容）'}</pre>
            </>
          ) : <Alert type="info" showIcon message="无内容" />}
        </Spin>
      </Drawer>

    </div>
  );
}
