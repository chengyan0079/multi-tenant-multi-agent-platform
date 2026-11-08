import { useEffect, useMemo, useState } from 'react';
import { Select, Space, Typography } from 'antd';
import {
  ProTable as AntProTable,
  type ProColumns,
  type ProTableProps,
} from '@ant-design/pro-components';

export type { ActionType, ProColumns } from '@ant-design/pro-components';

export type PinnableProTableProps<T extends Record<string, any> = Record<string, any>> =
  ProTableProps<T, any, any> & {
    /** localStorage 区分 key；不传则按 pathname + rowKey 自动生成 */
    pinStorageKey?: string;
    /** 默认固定列；不传则默认前两列 */
    defaultPinnedKeys?: string[];
  };

type PinOption = { value: string; label: string };

function columnKey<T extends Record<string, any>>(col: ProColumns<T>): string | undefined {
  const raw = col.key ?? col.dataIndex;
  if (typeof raw === 'string' || typeof raw === 'number') return String(raw);
  return undefined;
}

function buildPinOptions<T extends Record<string, any>>(
  columns: ProColumns<T>[],
): PinOption[] {
  const seen = new Set<string>();
  const options: PinOption[] = [];
  for (const col of columns) {
    const key = columnKey(col);
    if (!key || seen.has(key)) continue;
    if (col.hideInTable) continue;
    // 操作列不参与固定；分组列也不参与
    if (col.valueType === 'option' || key === 'action' || col.children) continue;
    seen.add(key);
    const title = typeof col.title === 'string' ? col.title : key;
    options.push({ value: key, label: title });
  }
  return options;
}

function readPinned(storageKey: string): string[] | null {
  try {
    const raw = localStorage.getItem(storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map(String) : null;
  } catch {
    return null;
  }
}

/**
 * 统一 ProTable：工具栏自动带「固定列」选择器。
 * 选中的列按原列顺序移到最左侧并加 fixed:left，保证固定列连续。
 */
export function ProTable<T extends Record<string, any> = Record<string, any>>(
  props: PinnableProTableProps<T>,
) {
  const {
    columns,
    pinStorageKey,
    defaultPinnedKeys,
    toolBarRender,
    options,
    rowKey,
    ...rest
  } = props;

  const safeColumns = (columns ?? []) as ProColumns<T>[];
  const pinOptions = useMemo(() => buildPinOptions(safeColumns), [safeColumns]);

  const storageKey = useMemo(() => {
    const suffix =
      pinStorageKey ??
      `${window.location.pathname}:${String(rowKey ?? 'table')}`;
    return `pinnable-columns:${suffix}`;
  }, [pinStorageKey, rowKey]);

  const [pinnedKeys, setPinnedKeys] = useState<string[]>(() => {
    const allowed = new Set(pinOptions.map((o) => o.value));
    const saved = readPinned(storageKey);
    if (saved) {
      const valid = saved.filter((k) => allowed.has(k));
      if (valid.length > 0) return valid;
    }
    const defaults = defaultPinnedKeys ?? pinOptions.slice(0, 2).map((o) => o.value);
    return defaults.filter((k) => allowed.has(k));
  });

  // 列变化（权限/配置）后剔除已不存在的固定列
  useEffect(() => {
    setPinnedKeys((prev) => {
      const allowed = new Set(pinOptions.map((o) => o.value));
      const next = prev.filter((k) => allowed.has(k));
      return next.length === prev.length ? prev : next;
    });
  }, [pinOptions]);

  const changePinned = (keys: string[]) => {
    setPinnedKeys(keys);
    try {
      localStorage.setItem(storageKey, JSON.stringify(keys));
    } catch {
      // 本地存储失败不影响当前使用
    }
  };

  const pinnedSet = new Set(pinnedKeys);
  const orderedColumns = [
    ...safeColumns.filter((col) => {
      const key = columnKey(col);
      return key ? pinnedSet.has(key) : false;
    }),
    ...safeColumns.filter((col) => {
      const key = columnKey(col);
      return key ? !pinnedSet.has(key) : true;
    }),
  ].map((col) => {
    const key = columnKey(col);
    if (!key || !pinnedSet.has(key)) return col;
    return {
      ...col,
      width: col.width ?? 160,
      fixed: 'left' as const,
      onHeaderCell: () => ({ style: { background: '#fafafa' } }),
      onCell: () => ({ style: { background: '#fff' } }),
    };
  });

  const pinControl = pinOptions.length > 0 ? (
    <Space size={4} key="__pin_columns__">
      <Typography.Text type="secondary">固定列</Typography.Text>
      <Select
        mode="multiple"
        size="small"
        placeholder="选择要固定的列"
        value={pinnedKeys}
        onChange={changePinned}
        options={pinOptions}
        allowClear
        maxTagCount="responsive"
        style={{ minWidth: 200, maxWidth: 360 }}
      />
    </Space>
  ) : null;

  const mergedOptions =
    options === false
      ? false
      : { ...(options ?? {}), setting: false };

  return (
    <AntProTable<T>
      {...rest}
      rowKey={rowKey}
      columns={orderedColumns}
      options={mergedOptions}
      toolBarRender={(action, rows) => [
        ...(pinControl ? [pinControl] : []),
        ...(typeof toolBarRender === 'function' ? toolBarRender(action, rows) : []),
      ]}
    />
  );
}

export default ProTable;
