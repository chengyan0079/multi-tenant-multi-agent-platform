/**
 * 日/夜主题：用 antd ConfigProvider 的 algorithm 切换，选择持久化到 localStorage。
 * 同时把当前模式写到 <html data-theme>，方便纯 CSS（如登录页背景）跟随切换。
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { theme as antdTheme } from 'antd';

export type ThemeMode = 'light' | 'dark';

interface ThemeContextValue {
  mode: ThemeMode;
  isDark: boolean;
  toggle: () => void;
  setMode: (mode: ThemeMode) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const STORAGE_KEY = 'app-theme-mode';

function readInitialMode(): ThemeMode {
  return localStorage.getItem(STORAGE_KEY) === 'dark' ? 'dark' : 'light';
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(readInitialMode);
  const isDark = mode === 'dark';

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, mode);
    document.documentElement.dataset.theme = mode;
  }, [mode]);

  const toggle = () => setMode((m) => (m === 'dark' ? 'light' : 'dark'));

  return (
    <ThemeContext.Provider value={{ mode, isDark, toggle, setMode }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useThemeMode(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error('useThemeMode 必须在 ThemeProvider 内使用');
  }
  return ctx;
}

/** 供 ConfigProvider.theme.algorithm 使用：深色走 darkAlgorithm，否则默认算法。 */
export function themeAlgorithm(isDark: boolean) {
  return isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm;
}
