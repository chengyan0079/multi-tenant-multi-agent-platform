import { useState } from 'react';
import { App as AntdApp, Button, Card, Input, Space, Typography, Upload } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd/es/upload/interface';
import { useNavigate } from 'react-router-dom';

import { uploadResume } from '../../services/resume';

const { Dragger } = Upload;
const MAX_MB = 20;

/** 简历上传页（resume:upload）：选择 PDF + 选填岗位/JD，提交后台异步评审。 */
export default function ResumeUpload() {
  const { message } = AntdApp.useApp();
  const navigate = useNavigate();
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [targetPosition, setTargetPosition] = useState('');
  const [jobDescription, setJobDescription] = useState('');
  const [uploading, setUploading] = useState(false);

  const doUpload = async () => {
    const f = fileList[0]?.originFileObj as File | undefined;
    if (!f) {
      message.warning('请先选择简历 PDF 文件');
      return;
    }
    if (!/\.pdf$/i.test(f.name)) {
      message.warning('仅支持 PDF 文件');
      return;
    }
    if (f.size > MAX_MB * 1024 * 1024) {
      message.warning(`文件超过 ${MAX_MB}MB 上限`);
      return;
    }
    setUploading(true);
    try {
      const r = await uploadResume(f, targetPosition.trim(), jobDescription.trim());
      message.success(`已提交评审，评审单号：${r.review_id}`);
      setFileList([]);
      setTargetPosition('');
      setJobDescription('');
      navigate('/resume/page');
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  };

  return (
    <Card title="简历上传" style={{ maxWidth: 720 }}>
      <Typography.Paragraph type="secondary">
        上传简历 PDF（≤{MAX_MB}MB），系统将在后台异步完成评审。可填写目标岗位与 JD 以提升评审针对性。
      </Typography.Paragraph>
      <Dragger
        accept=".pdf"
        beforeUpload={() => false}
        maxCount={1}
        fileList={fileList}
        onChange={({ fileList: fl }) => setFileList(fl)}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">点击或拖拽简历 PDF 到此区域</p>
        <p className="ant-upload-hint">仅支持 PDF；单文件上限 {MAX_MB}MB</p>
      </Dragger>
      <Space direction="vertical" style={{ width: '100%', marginTop: 16 }}>
        <Input
          placeholder="目标岗位（选填）"
          value={targetPosition}
          onChange={(e) => setTargetPosition(e.target.value)}
          maxLength={128}
        />
        <Input.TextArea
          placeholder="岗位 JD（选填）"
          value={jobDescription}
          onChange={(e) => setJobDescription(e.target.value)}
          rows={3}
          maxLength={2000}
        />
      </Space>
      <Space style={{ marginTop: 16 }}>
        <Button type="primary" loading={uploading} onClick={doUpload} disabled={fileList.length === 0}>
          提交评审
        </Button>
        <Button onClick={() => navigate('/resume/page')}>查看评审列表</Button>
      </Space>
    </Card>
  );
}
