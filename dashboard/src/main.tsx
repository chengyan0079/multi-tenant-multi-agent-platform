import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import 'antd/dist/reset.css';

import App from './App';
import { ThemeProvider, useThemeMode, themeAlgorithm } from './theme/ThemeProvider';
import './styles.css';

const FONT_FAMILY =
  "'PingFang SC', 'Microsoft YaHei', 'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif";

/** 品牌色板：靛蓝深空 + 青强调；深浅两套背景（避开纯白/纯黑）。 */
function buildTheme(isDark: boolean) {
  const common = {
    colorPrimary: '#3b5bdb',
    colorInfo: '#3b5bdb',
    colorSuccess: '#22a06b',
    colorWarning: '#e3a008',
    colorError: '#e5484d',
    borderRadius: 10,
    fontSize: 14,
    fontFamily: FONT_FAMILY,
    controlHeight: 34,
    wireframe: false,
  };
  const token = isDark
    ? {
        ...common,
        colorBgLayout: '#0d1422',
        colorBgContainer: '#121b2e',
        colorBgElevated: '#16223a',
      }
    : {
        ...common,
        colorBgLayout: '#eaeef6',
        colorBgContainer: '#fcfdff',
        colorBgElevated: '#ffffff',
      };
  return {
    algorithm: themeAlgorithm(isDark),
    token,
    cssVar: { key: 'ant' },
  };
}

/** 主题跟随：根据当前深浅模式切换 antd 算法，并开启 CSS 变量供 styles.css 引用。 */
function ThemedApp() {
  const { isDark } = useThemeMode();
  return (
    <ConfigProvider locale={zhCN} theme={buildTheme(isDark)}>
      <AntdApp>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AntdApp>
    </ConfigProvider>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <ThemedApp />
    </ThemeProvider>
  </React.StrictMode>,
);
