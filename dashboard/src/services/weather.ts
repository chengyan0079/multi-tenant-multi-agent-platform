/**
 * 当天天气（状态栏展示用）。
 *
 * 全部走免密第三方接口，不经过后端：
 * 1. `navigator.geolocation` 取经纬度（HTTP 非 localhost 或用户拒绝时降级到兜底城市）；
 * 2. BigDataCloud 反查城市名；
 * 3. Open-Meteo 取当前气温与天气码。
 *
 * 任一步失败都返回 null，由调用方降级成「天气暂不可用」，绝不阻塞页面渲染。
 */

export interface WeatherInfo {
  city: string;
  temp: number;
  text: string;
}

/** 同一会话内 30 分钟不重复打接口 */
const CACHE_KEY = 'app.weather.today';
const CACHE_TTL = 30 * 60 * 1000;

/** 定位不可用时的兜底城市 */
const FALLBACK = { city: '北京', latitude: 39.9042, longitude: 116.4074 };

/** WMO 天气码 → 中文（Open-Meteo 用 WMO 4677 编码） */
const WMO_TEXT: Record<number, string> = {
  0: '晴',
  1: '晴间多云',
  2: '多云',
  3: '阴',
  45: '雾',
  48: '雾凇',
  51: '毛毛雨',
  53: '小雨',
  55: '中雨',
  56: '冻雨',
  57: '冻雨',
  61: '小雨',
  63: '中雨',
  65: '大雨',
  66: '冻雨',
  67: '冻雨',
  71: '小雪',
  73: '中雪',
  75: '大雪',
  77: '雪粒',
  80: '阵雨',
  81: '强阵雨',
  82: '暴雨',
  85: '阵雪',
  86: '强阵雪',
  95: '雷阵雨',
  96: '雷阵雨伴冰雹',
  99: '雷阵雨伴冰雹',
};

interface OpenMeteoResp {
  current?: { temperature_2m?: number; weather_code?: number };
}

interface ReverseGeoResp {
  city?: string;
  locality?: string;
  principalSubdivision?: string;
  countryName?: string;
}

async function getJson<T>(url: string, timeoutMs = 6000): Promise<T> {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    window.clearTimeout(timer);
  }
}

function readCache(): WeatherInfo | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { at: number; data: WeatherInfo };
    if (!parsed?.data || Date.now() - parsed.at > CACHE_TTL) return null;
    return parsed.data;
  } catch {
    return null;
  }
}

function writeCache(data: WeatherInfo): void {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), data }));
  } catch {
    // 隐私模式写入失败，忽略即可
  }
}

function getPosition(): Promise<{ latitude: number; longitude: number } | null> {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ latitude: p.coords.latitude, longitude: p.coords.longitude }),
      () => resolve(null),
      { timeout: 4000, maximumAge: 10 * 60 * 1000 },
    );
  });
}

export async function fetchTodayWeather(): Promise<WeatherInfo | null> {
  const cached = readCache();
  if (cached) return cached;

  const pos = (await getPosition()) ?? FALLBACK;
  try {
    const [weather, geo] = await Promise.all([
      getJson<OpenMeteoResp>(
        `https://api.open-meteo.com/v1/forecast?latitude=${pos.latitude}&longitude=${pos.longitude}` +
          `&current=temperature_2m,weather_code&timezone=auto`,
      ),
      getJson<ReverseGeoResp>(
        `https://api.bigdatacloud.net/data/reverse-geocode-client` +
          `?latitude=${pos.latitude}&longitude=${pos.longitude}&localityLanguage=zh`,
      ).catch(() => null),
    ]);

    const temp = weather.current?.temperature_2m;
    const code = weather.current?.weather_code;
    if (typeof temp !== 'number') return null;

    const city =
      geo?.city || geo?.locality || geo?.principalSubdivision || geo?.countryName || FALLBACK.city;
    const data: WeatherInfo = {
      city,
      temp: Math.round(temp),
      text: (typeof code === 'number' ? WMO_TEXT[code] : undefined) ?? '未知',
    };
    writeCache(data);
    return data;
  } catch {
    return null;
  }
}
