import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Card, Descriptions, Spin, Tag, Typography, message } from 'antd';
import ChatBubble from '../../components/ChatBubble';
import { getAdminSession, type SessionDetail, type TurnReplay } from '../../services/unified';
import { renderEvent, ROUTE_MAP } from './renderers';

interface ReplayMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  events: { type: string; [k: string]: unknown }[];
}

function toReplay(turns: TurnReplay[]): ReplayMessage[] {
  const out: ReplayMessage[] = [];
  for (const t of turns) {
    if (t.user_content) {
      out.push({ id: `${t.turn_index}-u`, role: 'user', content: t.user_content, events: [] });
    }
    if (t.assistant_content || t.event_type) {
      out.push({
        id: `${t.turn_index}-a`,
        role: 'assistant',
        content: t.assistant_content ?? '',
        events: t.event_type ? [{ type: t.event_type, ...t.payload }] : [],
      });
    }
  }
  return out;
}

export default function UnifiedSessionDetail() {
  const { threadId } = useParams<{ threadId: string }>();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<SessionDetail | null>(null);

  const load = useCallback(async () => {
    if (!threadId) return;
    setLoading(true);
    try {
      setDetail(await getAdminSession(threadId));
    } catch {
      message.error('加载会话详情失败');
    } finally {
      setLoading(false);
    }
  }, [threadId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (!detail) {
    return <Typography.Text>会话不存在</Typography.Text>;
  }

  const onAction = (routeKey: string) => {
    const path = ROUTE_MAP[routeKey];
    if (path) navigate(path);
  };

  return (
    <div>
      <Button style={{ marginBottom: 12 }} onClick={() => navigate('/consultation/sessions')}>
        返回列表
      </Button>
      <Descriptions bordered size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="标题">{detail.title || '未命名会话'}</Descriptions.Item>
        <Descriptions.Item label="会话键">{detail.session_id}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag>{detail.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="Agent">
          {detail.agent_type ? <Tag color="blue">{detail.agent_type}</Tag> : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="轮数">{detail.turn_count}</Descriptions.Item>
      </Descriptions>
      <Card title="对话回放">
        {toReplay(detail.turns).map((m) => (
          <div key={m.id}>
            <ChatBubble role={m.role} content={m.content} markdown={m.role === 'assistant'} />
            {m.events.map((e, i) => (
              <div key={i}>{renderEvent(e as never, onAction)}</div>
            ))}
          </div>
        ))}
      </Card>
    </div>
  );
}
