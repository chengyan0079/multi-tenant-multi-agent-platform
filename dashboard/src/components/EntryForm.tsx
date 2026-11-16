import { useState } from 'react';
import { Button, Form, Input, InputNumber, Select, Space, Typography, Upload, message } from 'antd';
import type { UploadFile } from 'antd';
import type { AgentCapability } from '../services/unified';
import { uploadAttachment } from '../services/unified';

interface Props {
  spec: AgentCapability;
  onCancel: () => void;
  onSubmit: (entry: { name: string; value: string }[], fileRefs: string[]) => void;
}

/** 按 spec.entry_fields 动态渲染入口表单；accept_files 非空时附文件选择（两步上传拿 file_ref）。 */
export default function EntryForm({ spec, onCancel, onSubmit }: Props) {
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const setField = (name: string, v: unknown) => setValues((prev) => ({ ...prev, [name]: v }));

  const handleSubmit = async () => {
    // 必填校验
    for (const f of spec.entry_fields) {
      const v = values[f.name];
      if (f.required && (v === undefined || v === '' || v === null)) {
        message.warning(`请填写${f.label}`);
        return;
      }
    }
    setSubmitting(true);
    try {
      const fileRefs: string[] = [];
      if (files.length > 0) {
        for (const f of files) {
          if (!f.originFileObj) continue;
          const ref = await uploadAttachment(f.originFileObj as File, spec.agent_type);
          fileRefs.push(ref.file_ref);
        }
      }
      const entry = spec.entry_fields.map((f) => ({
        name: f.name,
        value: String(values[f.name] ?? ''),
      }));
      onSubmit(entry, fileRefs);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        border: '1px solid #e8e8e8',
        borderRadius: 8,
        padding: 16,
        margin: '12px 0',
        background: '#fafafa',
      }}
    >
      <Typography.Text strong>{spec.display_name} 入口信息</Typography.Text>
      <Form layout="vertical" style={{ marginTop: 12 }}>
        {spec.entry_fields.map((f) => (
          <Form.Item key={f.name} label={f.label} required={f.required}>
            {f.type === 'enum' ? (
              <Select
                value={values[f.name] as string}
                placeholder={`请选择${f.label}`}
                options={(f.options ?? []).map((o) => ({ label: o, value: o }))}
                onChange={(v) => setField(f.name, v)}
              />
            ) : f.type === 'int' || f.type === 'float' ? (
              <InputNumber
                style={{ width: '100%' }}
                value={values[f.name] as number}
                onChange={(v) => setField(f.name, v)}
              />
            ) : f.type === 'bool' ? (
              <Select
                value={values[f.name] as string}
                options={[
                  { label: '是', value: 'true' },
                  { label: '否', value: 'false' },
                ]}
                onChange={(v) => setField(f.name, v)}
              />
            ) : (
              <Input
                value={values[f.name] as string}
                onChange={(e) => setField(f.name, e.target.value)}
              />
            )}
          </Form.Item>
        ))}
        {spec.accept_files.length > 0 && (
          <Form.Item label="附件">
            <Upload
              multiple
              fileList={files}
              beforeUpload={() => false}
              onChange={({ fileList }) => setFiles(fileList)}
            >
              <Button>选择文件</Button>
            </Upload>
          </Form.Item>
        )}
      </Form>
      <Space>
        <Button type="primary" loading={submitting} onClick={handleSubmit}>
          开始
        </Button>
        <Button onClick={onCancel}>取消</Button>
      </Space>
    </div>
  );
}
