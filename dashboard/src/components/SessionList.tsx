import { Button, Empty, List, Popconfirm, Spin, Tag, Typography } from 'antd';
import type { SessionItem } from '../services/unified';

interface Props {
  loading: boolean;
  sessions: SessionItem[];
  activeId: string | null;
  onSelect: (s: SessionItem) => void;
  onNew: () => void;
  onDelete: (s: SessionItem) => void;
}

/** 会话列表（左侧栏）：新建 / 切换 / 删除，thread_id 为唯一键。 */
export default function SessionList({ loading, sessions, activeId, onSelect, onNew, onDelete }: Props) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0' }}>
        <Button type="primary" block onClick={onNew}>
          新会话
        </Button>
      </div>
      {loading ? (
        <div style={{ padding: 24, textAlign: 'center' }}>
          <Spin />
        </div>
      ) : sessions.length === 0 ? (
        <Empty
          style={{ marginTop: 48 }}
          description="暂无会话"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      ) : (
        <List
          style={{ flex: 1, overflow: 'auto' }}
          dataSource={sessions}
          renderItem={(s) => (
            <List.Item
              onClick={() => onSelect(s)}
              style={{
                cursor: 'pointer',
                padding: '10px 12px',
                background: s.thread_id === activeId ? '#e6f4ff' : undefined,
              }}
              actions={[
                <Popconfirm
                  key="del"
                  title="删除该会话？"
                  okText="删除"
                  cancelText="取消"
                  onConfirm={(e) => {
                    e?.stopPropagation();
                    onDelete(s);
                  }}
                >
                  <Typography.Link
                    onClick={(e) => e.stopPropagation()}
                    style={{ color: '#ff4d4f' }}
                  >
                    删除
                  </Typography.Link>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  <span>
                    {s.title || '未命名会话'}
                    {s.agent_type ? <Tag style={{ marginLeft: 6 }}>{s.agent_type}</Tag> : null}
                  </span>
                }
                description={
                  <span style={{ fontSize: 12, color: '#999' }}>
                    {s.status} · {s.turn_count} 轮
                  </span>
                }
              />
            </List.Item>
          )}
        />
      )}
    </div>
  );
}
