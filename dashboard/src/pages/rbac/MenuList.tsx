import { useCallback, useEffect, useRef, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
} from 'antd';
import { ProTable, type ProColumns, type ActionType } from '../../components/ProTable';
import {
  createMenu,
  deleteMenu,
  listMenus,
  setMenuStatus,
  updateMenu,
  type MenuNode,
} from '../../services/rbac';
import { hasScope } from '../../services/auth';
import { sortByTimeThenId } from '../../utils/sort';

export default function MenuList() {
  const { message } = AntdApp.useApp();
  const canAdd = hasScope('menu:add');
  const canUpdate = hasScope('menu:update');
  const canDelete = hasScope('menu:delete');
  const canStatus = hasScope('menu:status');
  const actionRef = useRef<ActionType>();
  const [parentItems, setParentItems] = useState<MenuNode[]>([]);
  const [togglingId, setTogglingId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<MenuNode | null>(null);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();

  const request = useCallback(async (params: any) => {
    const res = await listMenus(params.current ?? 1, params.pageSize ?? 50, {
      id: params.id,
      parent_id: params.parent_id,
      name: params.name,
      visible: params.visible,
    });
    return { data: sortByTimeThenId(res.items), success: true, total: res.total };
  }, []);

  useEffect(() => {
    listMenus(1, 200).then((r) => setParentItems(r.items)).catch(() => {});
  }, []);

  const openCreate = (parentId = 0) => {
    createForm.resetFields();
    createForm.setFieldsValue({ parent_id: parentId, visible: true, sort_order: 0 });
    setCreateOpen(true);
  };

  const openEdit = (node: MenuNode) => {
    setEditTarget(node);
    editForm.resetFields();
    editForm.setFieldsValue({
      name: node.name,
      path: node.path,
      icon: node.icon ?? '',
      parent_id: node.parent_id,
      sort_order: node.sort_order,
      visible: node.visible,
      scope: node.scope ?? '',
    });
    setEditOpen(true);
  };

  const onDelete = async (id: number) => {
    try {
      await deleteMenu(id);
      message.success('菜单已删除');
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const toggleVisible = async (node: MenuNode, visible: boolean) => {
    setTogglingId(node.id);
    try {
      await setMenuStatus(node.id, visible);
      message.success(visible ? '已显示' : '已隐藏');
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setTogglingId(null);
    }
  };

  type MenuValues = {
    name: string;
    path: string;
    icon?: string;
    parent_id: number;
    sort_order?: number;
    visible?: boolean;
    scope?: string;
  };

  const toPayload = (values: MenuValues) => ({
    name: values.name,
    path: values.path,
    icon: values.icon || '',
    parent_id: values.parent_id,
    sort_order: Number(values.sort_order) || 0,
    visible: values.visible ?? true,
    scope: values.scope || null,
  });

  const onCreate = async (values: MenuValues) => {
    try {
      await createMenu(toPayload(values));
      message.success('菜单已创建');
      setCreateOpen(false);
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const onEdit = async (values: MenuValues) => {
    if (!editTarget) return;
    try {
      await updateMenu(editTarget.id, toPayload(values));
      message.success('菜单已更新');
      setEditOpen(false);
      actionRef.current?.reload();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const columns: ProColumns<MenuNode>[] = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 70, search: true, valueType: 'digit' },
    { title: '名称', dataIndex: 'name', key: 'name', valueType: 'text' },
    { title: '路径', dataIndex: 'path', key: 'path', valueType: 'text', search: false },
    { title: '图标', dataIndex: 'icon', key: 'icon', search: false, render: (value: any) => value || '-' },
    { title: '父级ID', dataIndex: 'parent_id', key: 'parent_id', width: 90, search: true, valueType: 'digit' },
    { title: '排序', dataIndex: 'sort_order', key: 'sort_order', width: 80, search: false },
    {
      title: '权限点',
      dataIndex: 'scope',
      key: 'scope',
      valueType: 'text',
      search: false,
      render: (value: any) => value ?? '-',
    },
    {
      title: '启动状态',
      dataIndex: 'visible',
      key: 'visible',
      width: 90,
      search: true,
      valueType: 'select',
      valueEnum: {
        true: { text: '显示' },
        false: { text: '隐藏' },
      },
      render: (value: any, row: MenuNode) =>
        canStatus ? (
          <Switch
            checked={value}
            loading={togglingId === row.id}
            onChange={(checked) => toggleVisible(row, checked)}
          />
        ) : (
          <span>{value ? '显示' : '隐藏'}</span>
        ),
    },
    {
      title: '操作',
      key: 'action',
      search: false,
      render: (_, row) => (
        <Space size={4}>
          {canAdd && (
            <Button type="link" size="small" onClick={() => openCreate(row.id)}>
              加子项
            </Button>
          )}
          {canUpdate && (
            <Button type="link" size="small" onClick={() => openEdit(row)}>
              编辑
            </Button>
          )}
          {canDelete && (
            <Popconfirm
              title="确认删除该菜单？"
              description="删除后其子菜单也会一并移除"
              onConfirm={() => onDelete(row.id)}
              okText="删除"
              cancelText="取消"
            >
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  // 父级下拉用当前页菜单即可；跨页父级极少，简单起见不跨页聚合
  const parentOptions = [
    { value: 0, label: '顶级菜单' },
    ...parentItems.map((m) => ({ value: m.id, label: `${m.name} (${m.path})` })),
  ];

  return (
    <div>
      <ProTable<MenuNode>
        headerTitle="菜单管理"
        actionRef={actionRef}
        toolBarRender={() =>
          canAdd
            ? [
                <Button key="add" type="primary" onClick={() => openCreate(0)}>
                  新建顶级菜单
                </Button>,
              ]
            : []
        }
        rowKey="id"
        columns={columns}
        request={request}
        search={{ labelWidth: 'auto' }}
        options={{ fullScreen: true, setting: true, density: true, reload: true }}
        pagination={{ pageSize: 50, showSizeChanger: true }}
        scroll={{ x: 'max-content' }}
      />
      {/* 新建菜单：父级可选 */}
      <Modal
        title="新建菜单"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        okText="创建"
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" onFinish={onCreate}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="path" label="路径" rules={[{ required: true }]}>
            <Input placeholder="/example" />
          </Form.Item>
          <Form.Item name="icon" label="图标">
            <Input placeholder="如 MenuOutlined" />
          </Form.Item>
          <Form.Item name="parent_id" label="父级" rules={[{ required: true }]}>
            <Select options={parentOptions} />
          </Form.Item>
          <Form.Item name="sort_order" label="排序">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="scope" label="权限点(scope)">
            <Input placeholder="如 rbac:read，留空表示登录可见" />
          </Form.Item>
          <Form.Item name="visible" label="可见" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑菜单：父级不可调整，其余可改 */}
      <Modal
        title={`编辑菜单：${editTarget?.name ?? ''}`}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={() => editForm.submit()}
        okText="保存"
        destroyOnClose
      >
        <Form form={editForm} layout="vertical" onFinish={onEdit}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="path" label="路径" rules={[{ required: true }]}>
            <Input placeholder="/example" />
          </Form.Item>
          <Form.Item name="icon" label="图标">
            <Input placeholder="如 MenuOutlined" />
          </Form.Item>
          <Form.Item name="parent_id" label="父级" extra="编辑时不可调整父级">
            <Select options={parentOptions} disabled />
          </Form.Item>
          <Form.Item name="sort_order" label="排序">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="scope" label="权限点(scope)">
            <Input placeholder="如 rbac:read，留空表示登录可见" />
          </Form.Item>
          <Form.Item name="visible" label="可见" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
