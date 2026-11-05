import { useCallback, useEffect, useRef, useState } from 'react';
import { App as AntdApp, Button, Drawer, Form, Input, Modal, Popconfirm, Select, Space, Tag, Typography } from 'antd';
import { ProTable, type ProColumns, type ActionType } from '@ant-design/pro-components';
import {
  createRole,
  deleteRole,
  listRoles,
  listScopes,
  updateRole,
  updateRolePermissions,
  type RoleItem,
} from '../../services/rbac';
import { hasScope } from '../../services/auth';
import { sortByTimeThenId } from '../../utils/sort';

/** 权限点下拉选项：按资源（冒号前）分组，值即后端 Scope 原文 */
type ScopeGroup = { label: string; options: { label: string; value: string }[] };

export default function RoleList() {
  const { message, modal } = AntdApp.useApp();
  const actionRef = useRef<ActionType>();
  const [detail, setDetail] = useState<RoleItem | null>(null);
  const [editRole, setEditRole] = useState<RoleItem | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [permRole, setPermRole] = useState<RoleItem | null>(null);
  const [permScopes, setPermScopes] = useState<string[]>([]);
  const [savingPerms, setSavingPerms] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [scopeOptions, setScopeOptions] = useState<ScopeGroup[]>([]);
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();

  /** 权限点全量取自后端 Scope（GET /admin/scopes），新增权限点前端无需改动 */
  useEffect(() => {
    void listScopes()
      .then((codes) => {
        const groups = new Map<string, { label: string; value: string }[]>();
        for (const code of codes) {
          const resource = code.split(':')[0];
          const list = groups.get(resource) ?? [];
          list.push({ label: code, value: code });
          groups.set(resource, list);
        }
        setScopeOptions([...groups.entries()].map(([resource, options]) => ({ label: resource, options })));
      })
      .catch((e) => message.error(e instanceof Error ? e.message : String(e)));
  }, [message]);

  const request = useCallback(async (params: any) => {
    const r = await listRoles(params.current ?? 1, params.pageSize ?? 20);
    return { data: sortByTimeThenId(r.items), success: true, total: r.total };
  }, []);

  /** 详情只读 */
  const openDetail = (role: RoleItem) => setDetail(role);

  /** 编辑：只改名称/说明（权限点走「配置权限」） */
  const openEdit = (role: RoleItem) => {
    setEditRole(role);
    editForm.setFieldsValue({ name: role.name, description: role.description });
  };

  const submitEdit = async (values: { name: string; description?: string }) => {
    if (!editRole) return;
    setSavingEdit(true);
    try {
      await updateRole(editRole.role_id, values);
      message.success('角色已更新');
      setEditRole(null);
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSavingEdit(false);
    }
  };

  /** 配置权限：覆盖式写入，勾选结果即该角色全部权限点 */
  const openPerms = (role: RoleItem) => {
    setPermRole(role);
    setPermScopes(role.scopes);
  };

  const savePerms = async () => {
    if (!permRole) return;
    setSavingPerms(true);
    try {
      await updateRolePermissions(permRole.role_id, permScopes);
      message.success('权限点已更新');
      setPermRole(null);
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSavingPerms(false);
    }
  };

  const onDelete = async (roleId: number) => {
    try {
      await deleteRole(roleId);
      message.success('角色已删除');
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const onCreate = async (values: { name: string; description?: string; scopes: string[] }) => {
    setSaving(true);
    try {
      await createRole(values);
      message.success('角色已创建');
      setModalOpen(false);
      form.resetFields();
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const columns: ProColumns<RoleItem>[] = [
    { title: '角色ID', dataIndex: 'role_id', key: 'role_id', width: 90, search: false },
    { title: '名称', dataIndex: 'name', key: 'name', valueType: 'text' },
    { title: '说明', dataIndex: 'description', key: 'description', valueType: 'text' },
    {
      title: '权限点',
      dataIndex: 'scopes',
      key: 'scopes',
      search: false,
      width: 420,
      render: (value: any) => (
        <>
          {(value as string[]).map((s) => (
            <Tag key={s}>{s}</Tag>
          ))}
        </>
      ),
    },
    {
      title: '操作',
      key: 'action',
      search: false,
      width: 220,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <a onClick={() => openDetail(record)}>详情</a>
          {hasScope('role:update') && <a onClick={() => openEdit(record)}>编辑</a>}
          {hasScope('role:update') && <a onClick={() => openPerms(record)}>配置权限</a>}
          {hasScope('role:delete') && (
            <Popconfirm
              title="确认删除该角色？"
              description="删除后该角色下用户的角色关联将失效"
              onConfirm={() => onDelete(record.role_id)}
              okText="删除"
              cancelText="取消"
            >
              <a>删除</a>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <ProTable<RoleItem>
        headerTitle="角色管理"
        actionRef={actionRef}
        toolBarRender={() =>
          hasScope('role:add')
            ? [
                <Button key="add" type="primary" onClick={() => setModalOpen(true)}>
                  新建角色
                </Button>,
              ]
            : []
        }
        rowKey="role_id"
        columns={columns}
        request={request}
        search={{ labelWidth: 'auto' }}
        options={{ fullScreen: true, setting: true, density: true, reload: true }}
        pagination={{ pageSize: 20, showSizeChanger: true }}
        scroll={{ x: 1200 }}
      />
      <Drawer
        title={`角色详情 - ${detail?.name ?? ''}`}
        open={detail !== null}
        onClose={() => setDetail(null)}
        width={420}
      >
        {detail && (
          <>
            <p>
              <b>说明：</b>
              {detail.description || '-'}
            </p>
            <Typography.Title level={5}>权限点（{detail.scopes.length}）</Typography.Title>
            <Space size={[4, 8]} wrap>
              {detail.scopes.length ? (
                detail.scopes.map((s) => <Tag key={s}>{s}</Tag>)
              ) : (
                <Typography.Text type="secondary">无</Typography.Text>
              )}
            </Space>
          </>
        )}
      </Drawer>
      <Modal
        title="编辑角色"
        open={editRole !== null}
        onCancel={() => setEditRole(null)}
        onOk={() => editForm.submit()}
        confirmLoading={savingEdit}
        okText="保存"
        forceRender
      >
        <Form form={editForm} layout="vertical" onFinish={submitEdit}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入角色名称' }]}
            extra={editRole?.name === 'admin' ? '内置角色 admin 不可改名' : undefined}
          >
            <Input maxLength={64} disabled={editRole?.name === 'admin'} />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input maxLength={255} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={`配置权限 - ${permRole?.name ?? ''}`}
        open={permRole !== null}
        onCancel={() => setPermRole(null)}
        onOk={() => {
          if (!permRole) return;
          modal.confirm({
            title: '确认覆盖保存权限点？',
            content: '将清空该角色原有全部权限点并写入当前勾选项，影响线上鉴权',
            okText: '保存',
            cancelText: '取消',
            onOk: () => savePerms(),
          });
        }}
        confirmLoading={savingPerms}
        okText="保存权限点"
        width={640}
        destroyOnClose
      >
        <Typography.Paragraph type="secondary">
          覆盖保存：勾选结果即该角色的全部权限点，取消勾选会一并删除。
        </Typography.Paragraph>
        <Select
          mode="multiple"
          value={permScopes}
          onChange={(v: string[]) => setPermScopes(v)}
          options={scopeOptions}
          optionFilterProp="label"
          placeholder="选择权限点（可搜索）"
          style={{ width: '100%' }}
        />
      </Modal>
      <Modal
        title="新建角色"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={onCreate}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input />
          </Form.Item>
          <Form.Item
            name="scopes"
            label="权限点"
            rules={[{ required: true, message: '请至少选择一个权限点' }]}
          >
            <Select
              mode="multiple"
              options={scopeOptions}
              optionFilterProp="label"
              allowClear
              placeholder="选择权限点（可搜索）"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
