/** 文件管理接口（后端 /api/v1/admin/files；按租户隔离，超管查全部）。 */

import { API_BASE, ApiError, authHeaders, http, type ApiEnvelope } from './http';

export interface FileItem {
  id: number;
  tenant_id: number | null;
  uploader_user_id: number;
  original_name: string;
  file_name: string;
  file_size: number;
  content_type: string | null;
  file_ext: string | null;
  file_version: number;
  version_count?: number | null;
  checksum: string | null;
  remark: string | null;
  create_at: string;
  updated_at: string;
}

/** 详情：在 FileItem 基础上附带该逻辑文件的全部版本。 */
export interface FileDetail extends FileItem {
  versions: FileItem[];
}

export interface FileListResult {
  items: FileItem[];
  total: number;
  page: number;
  page_size: number;
}

export const listFiles = (params: {
  file_name?: string;
  tenant_id?: number;
  page?: number;
  page_size?: number;
} = {}) => {
  const qs = new URLSearchParams();
  if (params.file_name) qs.set('file_name', params.file_name);
  if (params.tenant_id) qs.set('tenant_id', String(params.tenant_id));
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const s = qs.toString();
  return http.get<FileListResult>(`/api/v1/admin/files${s ? '?' + s : ''}`);
};

export const getFile = (id: number) => http.get<FileDetail>(`/api/v1/admin/files/${id}`);

/** 上传限制（单文件上限 MB，由后端 FILE_MAX_UPLOAD_MB 配置）。 */
export const getFileConfig = () =>
  http.get<{ max_upload_mb: number }>('/api/v1/admin/files/config');

/** 上传（multipart/form-data）：不能走 JSON 封装，需 FormData + 自动 boundary。 */
export async function uploadFile(file: File, remark?: string): Promise<FileItem> {
  const form = new FormData();
  form.append('file', file);
  if (remark) form.append('remark', remark);

  const res = await fetch(`${API_BASE}/api/v1/admin/files/upload`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  });
  const isJson = (res.headers.get('content-type') ?? '').includes('application/json');
  const body = isJson ? ((await res.json()) as ApiEnvelope<FileItem>) : null;
  if (!res.ok || !body || body.code !== 0) {
    throw new ApiError(
      body?.msg || `上传失败：HTTP ${res.status}`,
      body?.code ?? res.status,
      res.status,
    );
  }
  return body.data as FileItem;
}

/** 下载：带鉴权拉 blob，再触发浏览器保存。 */
export async function downloadFile(id: number, fileName: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/admin/files/${id}/download`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    let msg = `下载失败：HTTP ${res.status}`;
    try {
      const body = (await res.json()) as ApiEnvelope<unknown>;
      if (body?.msg) msg = body.msg;
    } catch {
      /* 非 JSON 错误体忽略 */
    }
    throw new ApiError(msg, res.status, res.status);
  }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}
