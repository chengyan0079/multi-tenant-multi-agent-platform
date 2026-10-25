import { useEffect, useState } from 'react';
import { App as AntdApp, Button, Drawer, Form, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  createRole,
  deleteRole,
  listRoles,
  SCOPE_OPTIONS,
  updateRolePermissions,
  type RoleItem,
} from '../../services/rbac';

// 内置角色（业务键）不可删除，仅做展示
const BUILTIN_ROLE_IDS = [1, 2, 3, 5];

export default function RoleList() {
  const { message } = AntdApp.useApp();
  const [data, setData] = useState<RoleItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<RoleItem | null>(null);
  const [permScopes, setPermScopes] = useState<string[]>([]);
  const [savingPerms, setSavingPerms] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const load = () => {
    setLoading(true);
    listRoles()
      .then((r) => setData(r.items))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  /** 打开详情时把当前权限点灌进受控 Select；保存走覆盖接口（后端先清空再写） */
  const openDetail = (role: RoleItem) => {
    setDetail(role);
    setPermScopes(role.scopes);
  };

  const savePerms = async (roleId: number) => {
    setSavingPerms(true);
    try {
      await updateRolePermissions(roleId, permScopes);
      message.success('权限点已更新');
      setDetail(null);
      load();
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
      load();
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
      load();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<RoleItem> = [
    { title: '角色ID', dataIndex: 'role_id', key: 'role_id', width: 90 },
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '说明', dataIndex: 'description', key: 'description' },
    {
      title: '权限点',
      dataIndex: 'scopes',
      key: 'scopes',
      render: (scopes: string[]) => (
        <>
          {scopes.map((s) => (
            <Tag key={s}>{s}</Tag>
          ))}
        </>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_, record) => (
        <Space>
          <a onClick={() => openDetail(record)}>详情</a>
          {BUILTIN_ROLE_IDS.includes(record.role_id) ? (
            <Typography.Text type="secondary">内置不可删</Typography.Text>
          ) : (
            <a onClick={() => onDelete(record.role_id)}>删除</a>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        角色管理
        <Button type="primary" style={{ marginLeft: 16 }} onClick={() => setModalOpen(true)}>
          新建角色
        </Button>
      </Typography.Title>
      <Table<RoleItem>
        rowKey="role_id"
        loading={loading}
        columns={columns}
        dataSource={data}
        pagination={false}
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
              {detail.description}
            </p>
            <Typography.Title level={5}>权限点</Typography.Title>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
              覆盖保存：勾选结果即该角色的全部权限点，取消勾选会一并删除。
            </Typography.Paragraph>
            <Select
              mode="multiple"
              value={permScopes}
              onChange={(v: string[]) => setPermScopes(v)}
              options={SCOPE_OPTIONS}
              optionFilterProp="label"
              placeholder="选择权限点"
              style={{ width: '100%' }}
            />
            <Button
              type="primary"
              style={{ marginTop: 16 }}
              loading={savingPerms}
              onClick={() => savePerms(detail.role_id)}
            >
              保存权限点
            </Button>
          </>
        )}
      </Drawer>
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
            rules={[{ required: true, message: '至少输入一个权限点' }]}
          >
            <Select mode="tags" placeholder="输入或选择权限点（回车确认）" tokenSeparators={[',']} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
