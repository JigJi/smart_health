const API = '';

export type TimelineEvent = {
  kind: 'anomaly' | 'gap' | 'drift' | 'training' | 'annotation';
  start: string;
  end: string;
  days: number;
  severity: 'mild' | 'moderate' | 'severe' | 'info';
  label: string;
  context: Record<string, any>;
};

export type YearlySummary = {
  year: number;
  workouts: number;
  hours: number;
  active_kcal: number | null;
  avg_hr: number | null;
  avg_hr_max: number | null;
};

export type ZoneRow = {
  sport: string;
  zone: string;
  samples: number;
  pct: number;
};

export type DayStatus = {
  day: string;
  dow: string;
  status: 'normal' | 'warning' | 'bad' | 'no_data' | 'no_signal' | 'low_confidence';
  hrv_ms: number | null;
  rhr_bpm: number | null;
  hrv_z: number | null;
  rhr_z: number | null;
  hrv_baseline: number | null;
  rhr_baseline: number | null;
  hr_samples: number;
  reasons_th: string[];
  recommendation_th: string;
};

export type PersonalNorms = {
  hrv: { median: number; std: number; p25: number; p75: number; samples: number };
  rhr: { mean: number; std: number; p25: number; p75: number; samples: number };
};

export type DailyStatus = {
  days: DayStatus[];
  today: DayStatus | null;
  personal_norms: PersonalNorms;
};

export type RingDay = {
  day: string;
  active_kcal: number;
  active_kcal_goal: number;
  exercise_min: number;
  exercise_min_goal: number;
  stand_hours: number;
  stand_hours_goal: number;
  move_pct: number | null;
  exercise_pct: number | null;
  stand_pct: number | null;
};

/** Read uid from URL query param once (set by native iOS WebView) */
function getUid(): string {
  if (typeof window === 'undefined') return 'default';
  const params = new URLSearchParams(window.location.search);
  return params.get('uid') || 'default';
}

async function j<T>(path: string): Promise<T> {
  // Append uid as query param so Next.js API routes can forward it to backend
  const uid = getUid();
  const separator = path.includes('?') ? '&' : '?';
  const url = `${API}${path}${separator}uid=${uid}`;
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

export const api = {
  dailyStatus: (days = 35) => j<DailyStatus>(`/daily_status?days=${days}`),
  unifiedTimeline: () => j<TimelineEvent[]>('/analytics/timeline_unified'),
  yearly: () =>
    j<{ monthly: any[]; yearly: YearlySummary[]; sports: any[] }>(
      '/analytics/timeline'
    ),
  zones: () =>
    j<{
      max_hr: number;
      by_sport: ZoneRow[];
      polarization_365d: { bucket: string; samples: number; pct: number }[];
      recent_workouts: any[];
    }>('/analytics/zones'),
  illness: () => j<{ episode_count: number; episodes: any[]; flags: any[] }>('/analytics/illness'),
  rings: (days = 30) => j<RingDay[]>(`/metrics/rings?days=${days}`),
  hrv: (days = 90) => j<any[]>(`/metrics/hrv?days=${days}`),
  rhr: (days = 90) => j<any[]>(`/metrics/rhr?days=${days}`),
  recovery: (days = 30) => j<any[]>(`/recovery?days=${days}`),
  status: () => j<{ parquet_dir: string; files: Record<string, number> }>('/status'),
  today: (date?: string) => {
    // Forward ?mock=1 from the page URL so dev can preview the chart
    // with synthetic data when real parquet is stale.
    const mock = typeof window !== 'undefined' && window.location.search.includes('mock=1');
    const params = new URLSearchParams();
    if (date) params.set('date', date);
    if (mock) params.set('mock', '1');
    const qs = params.toString();
    return j<TodayData>(qs ? `/api/today?${qs}` : '/api/today');
  },
  calendar: (year?: number, month?: number) => {
    const params = new URLSearchParams();
    if (year) params.set('year', String(year));
    if (month) params.set('month', String(month));
    return j<CalendarMonth>(params.toString() ? `/api/calendar?${params}` : '/api/calendar');
  },
};

export type TodayData = {
  date: string;
  day_th: string;
  readiness: number;
  readiness_label: string;
  color: 'green' | 'yellow' | 'red';
  reason: string;
  signals: {
    hrv: { value: number | null; baseline: number | null; status: string };
    rhr: { value: number | null; baseline: number | null; status: string };
    sleep: { hours: number | null; quality: string; bedtime: string | null; wakeup: string | null };
    prev_steps: { value: number | null; status: string };
    streak: number;
  };
  strain: {
    score: number;
    label: string;
    active_kcal: number;
    steps: number;
    workouts: { type: string; duration_min: number; kcal: number; time?: string }[];
  };
  recovery: {
    score: number | null;
    hrv_score: number | null;
    rhr_score: number | null;
    sleep_score: number | null;
  };
  sleep: {
    hours: number | null;
    quality_label: string;
    bedtime: string | null;
    wakeup: string | null;
  } | null;
  stress: {
    acute: number | null;                  // alias for current (API stable)
    current: number | null;                 // latest sample — drives gauge position
    highest: number | null;                 // max stress today (Bevel's "Highest")
    lowest: number | null;                  // min stress today (Bevel's "Lowest")
    peak: number | null;                    // alias for highest
    peak_time: string | null;               // ISO time of highest moment
    avg: number | null;                     // mean across today (Bevel's "Average")
    timeline: { time: string; stress: number }[];
    latest_sample_time: string | null;      // latest stress sample (HR-derived now)
    latest_hr_sample_time: string | null;   // watch-worn signal — HR is dense (~6 min) so >30min stale = watch off
    cycle_start: string | null;             // ISO datetime — left edge of chart's 24h cycle (anchored at bedtime)
    weekly_avg: number | null;
    weekly_trend: number | null;
    cv: number | null;
    stability: 'stable' | 'variable' | 'unstable' | 'ไม่มีข้อมูล';
  };
  illness: {
    confidence: 'high' | 'medium' | 'low' | null;
    headline: string | null;
    signals: { metric: string; z?: number; delta?: number; msg: string }[];
    sustained: boolean;
  };
  tip: string;
  tips?: { category: string; headline: string; options: string[] }[];
  tips_personalized?: boolean;
  vitals?: {
    spo2: number | null;
    rr: number | null;
  };
  weather?: {
    temp: number | null;
    weather: string;
    pm25: number | null;
    pm25_label: string;
  };
};

export type CalendarDay = {
  date: string;
  score: number | null;
  color: string;
  has_workout: boolean;
};

export type CalendarMonth = {
  year: number;
  month: number;
  month_th: string;
  first_weekday: number;
  days: CalendarDay[];
};
