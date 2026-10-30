import { useEffect, useState } from 'react';
import { Avatar, Button, Tooltip } from 'antd';
import {
  BulbFilled,
  BulbOutlined,
  EnvironmentOutlined,
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';

import type { UserInfo } from '../services/auth';
import { fetchTodayWeather, type WeatherInfo } from '../services/weather';
import { useThemeMode } from '../theme/ThemeProvider';

const WEEK_TEXT = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

interface Props {
  user: UserInfo;
  onLogout: () => void;
}

/** 内容区顶部状态栏：左侧当天日期 + 城市天气，右侧主题切换与登录用户信息。 */
export default function AppStatusBar({ user, onLogout }: Props) {
  const { isDark, toggle } = useThemeMode();
  const [now, setNow] = useState(() => dayjs());
  const [weather, setWeather] = useState<WeatherInfo | null>(null);
  const [weatherLoaded, setWeatherLoaded] = useState(false);

  /** 每分钟刷新一次，跨零点/跨天时日期不会停在打开页面的那天 */
  useEffect(() => {
    const timer = window.setInterval(() => setNow(dayjs()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let alive = true;
    void fetchTodayWeather().then((info) => {
      if (!alive) return;
      setWeather(info);
      setWeatherLoaded(true);
    });
    return () => {
      alive = false;
    };
  }, []);

  const displayName = user.name || user.username || '未登录';
  const roleText = user.role;
  const tenantText = user.tenantName;
  const weatherText = weather
    ? `${weather.city} ${weather.text} ${weather.temp}℃`
    : weatherLoaded
      ? '天气暂不可用'
      : '天气加载中…';

  return (
    <div className="app-statusbar">
      <div className="app-statusbar-left">
        <span className="app-statusbar-date">{now.format('YYYY年MM月DD日')}</span>
        <span className="app-statusbar-week">{WEEK_TEXT[now.day()]}</span>
        <span className="app-statusbar-sep" aria-hidden="true" />
        <span className="app-statusbar-weather" title={weatherText}>
          <EnvironmentOutlined />
          {weatherText}
        </span>
      </div>
      <div className="app-statusbar-right">
        <Tooltip title={isDark ? '切换浅色' : '切换深色'}>
          <Button
            type="text"
            aria-label="切换主题"
            icon={isDark ? <BulbFilled /> : <BulbOutlined />}
            onClick={toggle}
          />
        </Tooltip>
        <span className="app-statusbar-sep" aria-hidden="true" />
        <div className="app-user">
          <Avatar size={30} className="app-user-avatar" icon={<UserOutlined />} />
          <div className="app-user-meta">
            <span className="app-user-name" title={displayName}>
              {displayName}
            </span>
            {(roleText || tenantText) && (
              <span className="app-user-sub" title={[roleText, tenantText].filter(Boolean).join(' · ')}>
                {roleText ? <span className="app-user-role">{roleText}</span> : null}
                {tenantText ? <span className="app-user-tenant">{tenantText}</span> : null}
              </span>
            )}
          </div>
          <span className="app-user-divider" aria-hidden="true" />
          <Tooltip title="退出登录">
            <Button
              type="text"
              className="app-user-logout"
              aria-label="退出登录"
              icon={<LogoutOutlined />}
              onClick={onLogout}
            />
          </Tooltip>
        </div>
      </div>
    </div>
  );
}
