import type { FC } from 'react';
import { Button, Card, Tag, Typography } from 'antd';
import type { UnifiedEvent } from '../../services/unified';

/** route_key → 结果页路径，与后端 ROUTE_KEYS 对齐；新增 Agent 只在此加一行。 */
export const ROUTE_MAP: Record<string, string> = {
  qa_results: '/agent/qa/results',
  interview_report: '/agent/interview/results/:id',
  exam_results: '/agent/exam/results',
  resume_reviews: '/agent/resume/analysis',
};

export interface CardProps {
  event: UnifiedEvent;
  onAction: (routeKey: string) => void;
}

const RoutingCard: FC<CardProps> = ({ event }) => (
  <Card size="small" style={{ margin: '8px 0' }}>
    <Typography.Text strong>路由决策</Typography.Text>
    <div>
      <Tag color="blue">{String(event.agent_type ?? '')}</Tag>
      <Tag>来源：{String(event.source ?? '')}</Tag>
      <Tag>模式：{String(event.execution_mode ?? '')}</Tag>
      {event.confidence != null && <Tag>置信度：{String(event.confidence)}</Tag>}
    </div>
    {event.reason ? <Typography.Text type="secondary">{String(event.reason)}</Typography.Text> : null}
  </Card>
);

const GuidanceCard: FC<CardProps> = ({ event, onAction }) => (
  <Card size="small" style={{ margin: '8px 0' }}>
    <Typography.Paragraph>{String(event.message ?? '')}</Typography.Paragraph>
    {event.route_key ? (
      <Button type="link" onClick={() => onAction(String(event.route_key))}>
        {String(event.action_label ?? '查看')}
      </Button>
    ) : null}
  </Card>
);

const PipelineCard: FC<CardProps> = ({ event }) => {
  const plan = event.plan as { title?: string; steps?: { label?: string }[] } | undefined;
  const content = event.content as string | undefined;
  return (
    <Card size="small" style={{ margin: '8px 0' }}>
      {plan?.title ? <Typography.Text strong>{plan.title}</Typography.Text> : null}
      {plan?.steps?.length ? (
        <ol style={{ paddingLeft: 20 }}>
          {plan.steps.map((s, i) => (
            <li key={i}>{s.label}</li>
          ))}
        </ol>
      ) : null}
      {content ? <Typography.Paragraph>{content}</Typography.Paragraph> : null}
    </Card>
  );
};

const TaskCard: FC<CardProps> = ({ event, onAction }) => (
  <Card size="small" style={{ margin: '8px 0' }}>
    <Tag color="processing">{String(event.event_type ?? 'task')}</Tag>
    {event.stage ? <Tag>{String(event.stage)}</Tag> : null}
    {event.detail ? <Typography.Text type="secondary">{String(event.detail)}</Typography.Text> : null}
    {event.artifact_type ? (
      <div style={{ marginTop: 6 }}>
        <Tag color="success">{String(event.artifact_type)}</Tag>
        {event.route_key ? (
          <Button type="link" onClick={() => onAction(String(event.route_key))}>
            查看结果
          </Button>
        ) : null}
      </div>
    ) : null}
  </Card>
);

const MetaTags: FC<CardProps> = ({ event }) => (
  <div style={{ fontSize: 12, color: '#999', margin: '4px 0' }}>
    {event.thread_id ? <span>thread: {String(event.thread_id)} </span> : null}
    {event.turn_id ? <span>turn: {String(event.turn_id)} </span> : null}
    {event.turn_index != null ? <span>idx: {String(event.turn_index)}</span> : null}
  </div>
);

const ErrorCard: FC<CardProps> = ({ event }) => (
  <Card size="small" style={{ margin: '8px 0', borderColor: '#ffccc7', background: '#fff2f0' }}>
    <Typography.Text type="danger">
      {event.code ? `[${String(event.code)}] ` : ''}
      {String(event.message ?? '生成异常')}
    </Typography.Text>
  </Card>
);

export const CARD_RENDERERS: Record<string, FC<CardProps>> = {
  routing_decision: RoutingCard,
  guidance: GuidanceCard,
  pipeline_plan: PipelineCard,
  pipeline_step_result: PipelineCard,
  pipeline_result: PipelineCard,
  task_started: TaskCard,
  task_progress: TaskCard,
  task_result: TaskCard,
  review_required: TaskCard,
  meta: MetaTags,
  error: ErrorCard,
};

/** 未知事件类型安全降级：不渲染，避免前端崩溃。 */
export function renderEvent(e: UnifiedEvent, onAction: (routeKey: string) => void) {
  const C = CARD_RENDERERS[e.type];
  return C ? <C event={e} onAction={onAction} /> : null;
}
