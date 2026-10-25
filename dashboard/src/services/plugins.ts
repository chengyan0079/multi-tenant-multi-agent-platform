/** 插件接口（后端 /api/v1/admin/plugins，只读：当前只有已注册能力清单）。 */

import { http } from './http';

export const listPlugins = () => http.get<{ capabilities: string[] }>('/api/v1/admin/plugins');
