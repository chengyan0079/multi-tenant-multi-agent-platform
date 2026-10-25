import { useEffect, useState } from 'react';
import {
  Alert,
  App as AntdApp,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Spin,
  Switch,
  Tree,
  Typography,
} from 'antd';
import type { DataNode } from 'antd/es/tree';
import { createMenu, deleteMenu, listMenus, updateMenu, type MenuNode } from '../../services/rbac';

export default function MenuList() {
  const { message } = AntdApp.useApp();
  const [tree, setTree] = useState<MenuNode[]>([]);
  const [flat, setFlat] = useState<MenuNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<MenuNode | null>(null);
  const [form] = Form.useForm();

  const load = () => {
    setLoading(true);
    setError(null);
    listMenus()
      .then((r) => {
        setTree(r.items);
        setFlat(flatten(r.items));
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const flatten = (nodes: MenuNode[]): MenuNode[] => {
    const out: MenuNode[] = [];
    const walk = (ns: MenuNode[]) => {
      ns.forEach((n) => {
        out.push(n);
        if (n.children) walk(n.children);
      });
    };
    walk(nodes);
    return out;
  };

  const toTreeData = (nodes: MenuNode[]): DataNode[] =>
    nodes.map((n) => ({
      key: n.id,
      title: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <span>
            {n.name} <Typography.Text type="secondary">({n.path})</Typography.Text>
          </span>
          <Button size="small" type="link" onClick={() => openCreate(n.id)}>
            加子项
          </Button>
          <Button size="small" type="link" onClick={() => openEdit(n)}>
            编辑
          </Button>
          <Button size="small" type="link" danger onClick={() => onDelete(n.id)}>
            删除
          </Button>
        </span>
      ),
      children: n.children ? toTreeData(n.children) : [],
    }));

  const openCreate = (parentId = 0) => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ parent_id: parentId, visible: true, sort_order: 0 });
    setModalOpen(true);
  };

  const openEdit = (node: MenuNode) => {
    setEditing(node);
    form.resetFields();
    form.setFieldsValue({
      name: node.name,
      path: node.path,
      icon: node.icon ?? '',
      parent_id: node.parent_id,
      sort_order: node.sort_order,
      visible: node.visible,
      scope: node.scope ?? '',
    });
    setModalOpen(true);
  };

  const onDelete = async (id: number) => {
    try {
      await deleteMenu(id);
      message.success('菜单已删除');
      load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  const onSubmit = async (values: {
    name: string;
    path: string;
    icon?: string;
    parent_id: number;
    sort_order?: number;
    visible?: boolean;
    scope?: string;
  }) => {
    const payload = {
      name: values.name,
      path: values.path,
      icon: values.icon || '',
      parent_id: values.parent_id,
      sort_order: Number(values.sort_order) || 0,
      visible: values.visible ?? true,
      scope: values.scope || null,
    };
    try {
      if (editing) {
        await updateMenu(editing.id, payload);
        message.success('菜单已更新');
      } else {
        await createMenu(payload);
        message.success('菜单已创建');
      }
      setModalOpen(false);
      load();
    } catch (e) {
      message.error((e as Error).message);
    }
  };

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        菜单管理
        <Button type="primary" style={{ marginLeft: 16 }} onClick={() => openCreate(0)}>
          新建顶级菜单
        </Button>
      </Typography.Title>
      {error && (
        <Alert
          type="error"
          showIcon
          style={{ marginTop: 16 }}
          message={`加载失败：${error}`}
          action={
            <Button size="small" onClick={load}>
              重试
            </Button>
          }
        />
      )}
      <Spin spinning={loading}>
        <Tree treeData={toTreeData(tree)} defaultExpandAll style={{ marginTop: 16 }} />
      </Spin>
      <Modal
        title={editing ? '编辑菜单' : '新建菜单'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={onSubmit}>
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
            <Select
              options={[
                { value: 0, label: '顶级菜单' },
                ...flat.map((m) => ({ value: m.id, label: `${m.name} (${m.path})` })),
              ]}
            />
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
