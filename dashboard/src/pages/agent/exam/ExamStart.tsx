import { useState } from 'react';
import {
  App as AntdApp,
  Button,
  Card,
  Drawer,
  Input,
  InputNumber,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd';
import type { UploadProps } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { InboxOutlined } from '@ant-design/icons';
import { ProTable, type ProColumns } from '../../../components/ProTable';

type UploadFile = NonNullable<UploadProps['fileList']>[number];

// 试卷字段参考 agent_exams
interface ExamRow {
  examId: string;
  title: string;
  description: string;
  dueDate: string;
  isActive: boolean;
  questionCount: number;
}

// 评卷明细参考 agent_exam_reviews（教师评分 / 评语）
interface GradeItem {
  questionNo: number;
  knowledgeTag: string;
  aiScore: number;
  maxScore: number;
}

const MOCK_EXAMS: ExamRow[] = [
  {
    examId: 'exam-1001',
    title: 'Java 后端工程师-基础能力测评',
    description: '覆盖集合、并发、JVM、数据库',
    dueDate: '2026-11-30 23:59',
    isActive: true,
    questionCount: 3,
  },
  {
    examId: 'exam-1002',
    title: '前端工程师-进阶测评',
    description: '覆盖 React、CSS、工程化',
    dueDate: '2026-12-15 23:59',
    isActive: true,
    questionCount: 3,
  },
  {
    examId: 'exam-1003',
    title: '数据分析-基础测评',
    description: '覆盖 SQL、统计、可视化',
    dueDate: '2026-10-01 23:59',
    isActive: false,
    questionCount: 3,
  },
];

const MOCK_GRADE_ITEMS: GradeItem[] = [
  { questionNo: 1, knowledgeTag: '集合框架', aiScore: 10, maxScore: 10 },
  { questionNo: 2, knowledgeTag: '并发编程', aiScore: 8, maxScore: 10 },
  { questionNo: 3, knowledgeTag: 'JVM', aiScore: 9, maxScore: 10 },
];

/** 开始考试（mock）：试卷列表 + 上传试卷 + 老师评卷。 */
export default function ExamStart() {
  const { message } = AntdApp.useApp();
  const [exams, setExams] = useState<ExamRow[]>(MOCK_EXAMS);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [gradeExam, setGradeExam] = useState<ExamRow | null>(null);
  const [teacherScores, setTeacherScores] = useState<Record<number, number>>({});
  const [comments, setComments] = useState<Record<number, string>>({});

  const openUpload = () => {
    setFileList([]);
    setUploadOpen(true);
  };

  const submitUpload = () => {
    if (fileList.length === 0) {
      message.warning('请先选择试卷文件');
      return;
    }
    const name = fileList[0].name;
    setExams((prev) => [
      {
        examId: `exam-${Date.now()}`,
        title: name.replace(/\.[^.]+$/, ''),
        description: '新上传试卷（mock）',
        dueDate: '-',
        isActive: true,
        questionCount: 0,
      },
      ...prev,
    ]);
    message.success(`试卷上传成功：${name}（mock）`);
    setUploadOpen(false);
    setFileList([]);
  };

  const openGrade = (row: ExamRow) => {
    setGradeExam(row);
    setTeacherScores({});
    setComments({});
  };

  const submitGrade = () => {
    message.success('评卷已提交（mock）');
    setGradeExam(null);
    setTeacherScores({});
    setComments({});
  };

  const columns: ProColumns<ExamRow>[] = [
    { title: '试卷ID', dataIndex: 'examId', width: 120 },
    { title: '试卷', dataIndex: 'title', ellipsis: true },
    { title: '说明', dataIndex: 'description', ellipsis: true },
    { title: '题数', dataIndex: 'questionCount', width: 80 },
    { title: '截止时间', dataIndex: 'dueDate', width: 170 },
    {
      title: '状态',
      dataIndex: 'isActive',
      width: 90,
      render: (_, row) =>
        row.isActive ? <Tag color="green">可参加</Tag> : <Tag color="default">已截止</Tag>,
    },
    {
      title: '操作',
      width: 110,
      valueType: 'option',
      render: (_, row) => (
        <Button type="link" size="small" onClick={() => openGrade(row)}>
          老师评卷
        </Button>
      ),
    },
  ];

  const gradeColumns: ColumnsType<GradeItem> = [
    { title: '题号', dataIndex: 'questionNo', width: 70 },
    {
      title: '知识点',
      dataIndex: 'knowledgeTag',
      width: 110,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: 'AI 评分',
      dataIndex: 'aiScore',
      width: 100,
      render: (v: number, row) => `${v} / ${row.maxScore}`,
    },
    {
      title: '教师评分',
      dataIndex: 'aiScore',
      width: 130,
      render: (_, row) => (
        <InputNumber
          min={0}
          max={row.maxScore}
          value={teacherScores[row.questionNo] ?? row.aiScore}
          onChange={(v) =>
            setTeacherScores((prev) => ({ ...prev, [row.questionNo]: Number(v ?? 0) }))
          }
          style={{ width: '100%' }}
        />
      ),
    },
    {
      title: '评语',
      dataIndex: 'knowledgeTag',
      render: (_, row) => (
        <Input
          value={comments[row.questionNo] ?? ''}
          placeholder="可选"
          onChange={(e) =>
            setComments((prev) => ({ ...prev, [row.questionNo]: e.target.value }))
          }
        />
      ),
    },
  ];

  return (
    <Card
      title={<Typography.Title level={4} style={{ margin: 0 }}>开始考试</Typography.Title>}
      extra={
        <Button type="primary" onClick={openUpload}>
          上传试卷
        </Button>
      }
    >
      <ProTable<ExamRow>
        rowKey="examId"
        search={false}
        options={false}
        columns={columns}
        dataSource={exams}
        pagination={false}
        scroll={{ x: 'max-content' }}
      />

      <Modal
        title="上传试卷"
        open={uploadOpen}
        onCancel={() => setUploadOpen(false)}
        onOk={submitUpload}
        okText="上传"
        cancelText="取消"
      >
        <Upload.Dragger
          beforeUpload={() => false}
          maxCount={1}
          fileList={fileList}
          onChange={({ fileList: fl }) => setFileList(fl)}
          accept=".pdf,.doc,.docx"
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽试卷文件到此处</p>
          <p className="ant-upload-hint">支持 PDF / Word（mock 上传，不调后端）</p>
        </Upload.Dragger>
      </Modal>

      <Drawer
        title={gradeExam ? `老师评卷 · ${gradeExam.title}` : '老师评卷'}
        width={800}
        open={gradeExam !== null}
        onClose={() => setGradeExam(null)}
        footer={
          <Space style={{ float: 'right' }}>
            <Button onClick={() => setGradeExam(null)}>取消</Button>
            <Button type="primary" onClick={submitGrade}>
              提交评卷
            </Button>
          </Space>
        }
      >
        <Table<GradeItem>
          rowKey="questionNo"
          size="small"
          columns={gradeColumns}
          dataSource={MOCK_GRADE_ITEMS}
          pagination={false}
        />
      </Drawer>
    </Card>
  );
}
