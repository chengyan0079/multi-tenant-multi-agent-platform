import { useCallback, useEffect, useState } from 'react';
import {
  App as AntdApp,
  Button,
  Card,
  Descriptions,
  Divider,
  Popconfirm,
  Space,
  Tag,
  Typography,
} from 'antd';
import { useNavigate, useParams } from 'react-router-dom';
import dayjs from 'dayjs';

import { deleteReview, getReview, type ResumeDetail } from '../../services/resume';
import { hasScope } from '../../services/auth';

const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  processing: 'processing',
  done: 'success',
  completed: 'success',
  failed: 'error',
};

/** 评审查看页（resume:view）：展示单条评审结果（评分/维度/问题/总结），删除按 scope 门控。 */
export default function ResumeView() {
  const { id = '' } = useParams();
  const { message } = AntdApp.useApp();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ResumeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      setDetail(await getReview(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleDelete = async () => {
    try {
      await deleteReview(id);
      message.success('已删除');
      navigate('/resume/page');
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    }
  };

  if (error) {
    return (
      <Card>
        <Typography.Text type="danger">加载失败：{error}</Typography.Text>
        <Divider />
        <Button onClick={() => navigate('/resume/page')}>返回列表</Button>
      </Card>
    );
  }

  const d = detail;
  return (
    <Card
      title={`评审查看${d ? ` · ${d.review_id.slice(0, 8)}…` : ''}`}
      loading={loading && !d}
      extra={
        <Space>
          {hasScope('resume:delete') && d && (
            <Popconfirm title="确认删除该评审记录？" okText="删除" cancelText="取消" onConfirm={handleDelete}>
              <Button danger>删除</Button>
            </Popconfirm>
          )}
          <Button onClick={() => navigate('/resume/page')}>返回列表</Button>
        </Space>
      }
    >
      {d && (
        <>
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="状态">
              <Tag color={STATUS_COLOR[d.status] ?? 'processing'}>{d.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="综合得分">
              {d.weighted_score == null ? '-' : d.weighted_score.toFixed(1)}
            </Descriptions.Item>
            <Descriptions.Item label="上传时间">
              {d.created_at ? dayjs(d.created_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="更新时间">
              {d.updated_at ? dayjs(d.updated_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="PDF 路径" span={2}>
              <code style={{ wordBreak: 'break-all' }}>{d.pdf_minio_path}</code>
            </Descriptions.Item>
            {d.error_msg && (
              <Descriptions.Item label="错误信息" span={2}>
                <Typography.Text type="danger">{d.error_msg}</Typography.Text>
              </Descriptions.Item>
            )}
          </Descriptions>

          {d.status === 'processing' && (
            <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>
              评审仍在后台进行，请稍后刷新查看结果。
            </Typography.Paragraph>
          )}

          {d.summary && (
            <>
              <Divider>评审总结</Divider>
              {d.summary.overall_comment ? (
                <Typography.Paragraph>{d.summary.overall_comment}</Typography.Paragraph>
              ) : null}
              {d.summary.fit_assessment ? (
                <Typography.Paragraph type="secondary">
                  岗位匹配度：{d.summary.fit_assessment}
                </Typography.Paragraph>
              ) : null}
              {d.summary.highlights?.length ? (
                <ul>
                  {d.summary.highlights.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              ) : null}
            </>
          )}

          {d.dimension_scores && d.dimension_scores.length > 0 && (
            <>
              <Divider>维度评分</Divider>
              <Space wrap>
                {d.dimension_scores.map((dim) => (
                  <Tag key={dim.dimension} color="blue">
                    {dim.dimension}：{dim.score}
                  </Tag>
                ))}
              </Space>
            </>
          )}

          {d.issues && d.issues.length > 0 && (
            <>
              <Divider>改进建议</Divider>
              <ul>
                {d.issues.map((it, i) => (
                  <li key={i}>
                    [{it.priority}] {it.description}（{it.location}）：{it.suggestion}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </Card>
  );
}
