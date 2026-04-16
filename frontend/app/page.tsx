'use client';

import { useEffect, useState } from 'react';
import { api, TodayData, CalendarMonth } from '@/lib/api';

// localStorage key for stale-while-revalidate dashboard cache.
// Bump the version suffix when TodayData schema changes so old payloads
// (with missing/renamed fields) get discarded instead of crashing render.
const CACHE_KEY = 'smart_health_today_v1';

/* ─── Score label based on actual signals ─── */
function scoreLabel(data: TodayData): string {
  const { signals, strain } = data;
  const sleep = signals.sleep.hours;
  const streak = signals.streak;

  // Red zone
  if (data.readiness < 35) {
    if (sleep != null && sleep < 5) return 'นอนน้อย';
    if (streak >= 4) return 'โหมเกิน';
    return 'ต้องพัก';
  }

  // Yellow zone
  if (data.readiness < 50) {
    if (sleep != null && sleep < 6) return 'นอนน้อย';
    if (streak >= 3) return 'ล้าสะสม';
    return 'เหนื่อยอยู่';
  }

  // Green zone
  if (data.readiness >= 70) return 'พร้อมลุย';
  return 'พร้อม';
}

/* ─── Color constants ─── */
const COLORS: Record<string, { ring: string; glow: string }> = {
  green: { ring: '#30D158', glow: 'rgba(48,209,88,0.25)' },
  yellow: { ring: '#FF9F0A', glow: 'rgba(255,159,10,0.25)' },
  red: { ring: '#FF453A', glow: 'rgba(255,69,58,0.25)' },
};

/* ─── Score Ring with glow ─── */
function ScoreRing({ score, color, size = 160, label }: {
  score: number;
  color: 'green' | 'yellow' | 'red';
  size?: number;
  label: string;
}) {
  const c = COLORS[color];
  const stroke = 7;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (score / 100) * circ;

  return (
    <div className="relative flex items-center justify-center">
      <svg width={size} height={size} className="-rotate-90 relative z-10">
        {/* Track */}
        <circle cx={size/2} cy={size/2} r={r}
          fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={stroke} />
        {/* Progress */}
        <circle cx={size/2} cy={size/2} r={r}
          fill="none" stroke={c.ring} strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circ} strokeDashoffset={offset}
          style={{
            transition: 'stroke-dashoffset 1.5s cubic-bezier(0.16,1,0.3,1)',
            filter: `drop-shadow(0 0 8px ${c.ring})`,
          }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center z-20 pt-2">
        <div className="flex flex-col items-center" style={{ color: c.ring, textShadow: `0 0 20px ${c.glow}` }}>
          <div className="flex items-baseline">
            <span className="font-semibold" style={{ fontSize: size * 0.32 }}>{score}</span>
            <span className="font-light" style={{ fontSize: size * 0.14 }}>%</span>
          </div>
          <span className="text-[11px] tracking-widest text-white text-center leading-tight -mt-1" style={{ textShadow: 'none' }}>ความพร้อม<br/>ร่างกาย</span>
        </div>
      </div>
    </div>
  );
}

/* ─── Mini metric bar ─── */
function MiniMetric({ label, value, color, zone }: {
  label: string; value: number | null; color: string;
  zone?: [number, number];
}) {
  const v = value ?? 0;
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-base text-white">{label}</span>
        <span className="text-lg font-semibold" style={{ color }}>{value != null ? `${value}%` : '—'}</span>
      </div>
      <div className="relative w-full h-[5px] rounded-full bg-white/[0.06]">
        <div className="h-[5px] rounded-full transition-all duration-1000" style={{
          width: `${v}%`, background: `linear-gradient(90deg, ${color}80, ${color})`,
          boxShadow: `0 0 8px ${color}40`,
        }} />
        {zone && (
          <div className="absolute top-0 h-[5px] border-l border-r border-white/10"
            style={{ left: `${zone[0]}%`, width: `${zone[1] - zone[0]}%` }} />
        )}
      </div>
    </div>
  );
}

/* ─── Signal detail row ─── */
function SignalRow({ label, value, baseline, unit, status, sub, format }: {
  label: string; value: number | null; baseline: number | null;
  unit: string; status: string; sub?: string;
  format?: (v: number) => string;
}) {
  const statusColors: Record<string, string> = {
    good: '#30D158', normal: 'rgba(255,255,255,0.5)',
    warning: '#FF9F0A', bad: '#FF453A', no_data: 'rgba(255,255,255,0.2)',
  };
  const c = statusColors[status] || statusColors.normal;
  const display = value != null ? (format ? format(value) : `${value}`) : '—';

  return (
    <div className="flex items-center justify-between py-3">
      <div>
        <p className="text-sm text-white/70">{label}</p>
        {sub && <p className="text-[12px] text-white/30 mt-0.5">{sub}</p>}
        {baseline != null && <p className="text-[12px] text-white/30 mt-0.5">ปกติ {baseline} {unit}</p>}
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-sm font-medium" style={{ color: c }}>{display}</span>
        <span className="text-xs text-white/25">{unit}</span>
      </div>
    </div>
  );
}

/* ─── Monochrome SVG Icons ─── */
const IC = "rgba(255,255,255,0.35)";
const IconHeart = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={IC} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
  </svg>
);
const IconWave = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={IC} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="2 12 5 7 8 15 11 9 14 17 17 6 20 12 22 12"/>
  </svg>
);
const IconLung = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={IC} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 4v8"/><path d="M8 12c-2 0-4 1-4 4s2 4 4 4"/><path d="M16 12c2 0 4 1 4 4s-2 4-4 4"/>
    <path d="M8 12c0-2-1-4-1-6s1-2 2-2h2"/><path d="M16 12c0-2 1-4 1-6s-1-2-2-2h-2"/>
  </svg>
);
const IconO2 = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={IC} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="10" cy="12" r="5"/><path d="M18 8v2a2 2 0 0 0 2 2 2 2 0 0 0-2 2v2"/>
  </svg>
);
const IconMoon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={IC} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
  </svg>
);
const IconSteps = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={IC} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 16v-2a4 4 0 0 1 4-4h0"/><path d="M14 10h0a4 4 0 0 1 4 4v2"/>
    <circle cx="8" cy="6" r="2"/><circle cx="16" cy="6" r="2"/>
  </svg>
);

/* ─── Monitor Card (Bevel-style grid) ─── */
function MonitorCard({ icon, label, value, unit, status, baseline, sub, format }: {
  icon: React.ReactNode; label: string; value: number | null; unit: string;
  status: string; baseline?: number | null; sub?: string;
  format?: (v: number) => string;
}) {
  const statusColors: Record<string, string> = {
    good: '#30D158', normal: 'rgba(255,255,255,0.5)',
    warning: '#FF9F0A', bad: '#FF453A', no_data: 'rgba(255,255,255,0.2)',
  };
  const statusLabels: Record<string, string> = {
    good: 'ปกติ', normal: '', warning: 'ระวัง', bad: 'ผิดปกติ', no_data: '',
  };
  const c = statusColors[status] || statusColors.normal;
  const display = value != null ? (format ? format(value) : `${value}`) : '—';

  return (
    <div className="glass-card px-3.5 py-2.5 flex items-center justify-between">
      <div className="flex items-center gap-1.5">
        {icon}
        <span className="text-sm text-white/40">{label}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-base font-semibold text-white/90">{display}</span>
        <span className="text-[11px] text-white/30">{value != null ? unit : ''}</span>
        {value != null && statusLabels[status] ? (
          <div className="w-[5px] h-[5px] rounded-full ml-0.5" style={{ background: c }} />
        ) : null}
      </div>
    </div>
  );
}

/* ─── Workout icons ─── */
const WK_ICON: Record<string, string> = {
  TraditionalStrengthTraining: '🏋️', FunctionalStrengthTraining: '🏋️',
  Elliptical: '🚶', Cycling: '🚴', Boxing: '🥊',
  CoreTraining: '💪', HIIT: '⚡', CardioDance: '💃',
  Walking: '🚶', Running: '🏃', Yoga: '🧘',
  Swimming: '🏊', TableTennis: '🏓',
};

/* ─── Workout names ─── */
const WK: Record<string, string> = {
  TraditionalStrengthTraining: 'Strength', FunctionalStrengthTraining: 'Functional',
  Elliptical: 'Elliptical', Cycling: 'Cycling', Boxing: 'Boxing',
  CoreTraining: 'Core', HighIntensityIntervalTraining: 'HIIT', CardioDance: 'Dance',
  Walking: 'Walk', Running: 'Run', Yoga: 'Yoga',
  Swimming: 'Swim', TableTennis: 'Table Tennis',
};

/* ─── Main page ─── */
export default function Home() {
  const [data, setData] = useState<TodayData | null>(null);
  const [calData, setCalData] = useState<CalendarMonth | null>(null);
  const [calYear, setCalYear] = useState(new Date().getFullYear());
  const [calMonth, setCalMonth] = useState(new Date().getMonth() + 1);
  const [showCal, setShowCal] = useState(false);
  const [selectedDate, setSelectedDate] = useState<string | undefined>();
  const [error, setError] = useState(false);
  const [showTips, setShowTips] = useState(false);

  // All loads are silent — the UI shows previous data while new data fetches
  // in the background, then swaps in when ready. No blocking overlay anywhere
  // except the very first cold-start render (no cache + no response yet).
  const loadDay = (date?: string) => {
    api.today(date).then(d => {
      setData(d);
      // Persist "today" payload for next session's first paint (SWR pattern).
      // Skip when a specific date was requested — only the default "today" view
      // is what users land on first, so that's the only one worth caching.
      if (!date) {
        try { localStorage.setItem(CACHE_KEY, JSON.stringify(d)); } catch {}
      }
    }).catch(() => setError(true));
  };

  const loadCalendar = (y: number, m: number) => {
    api.calendar(y, m).then(setCalData).catch(() => {});
  };

  const prevMonth = () => {
    const m = calMonth === 1 ? 12 : calMonth - 1;
    const y = calMonth === 1 ? calYear - 1 : calYear;
    setCalMonth(m); setCalYear(y); loadCalendar(y, m);
  };

  const nextMonth = () => {
    const now = new Date();
    const m = calMonth === 12 ? 1 : calMonth + 1;
    const y = calMonth === 12 ? calYear + 1 : calYear;
    if (y > now.getFullYear() || (y === now.getFullYear() && m > now.getMonth() + 1)) return;
    setCalMonth(m); setCalYear(y); loadCalendar(y, m);
  };

  useEffect(() => {
    // Stale-while-revalidate: hydrate from cache for instant first paint,
    // then fetch fresh data silently in background. Bumps cache key on
    // schema change so old payloads don't crash render.
    try {
      const cached = localStorage.getItem(CACHE_KEY);
      if (cached) setData(JSON.parse(cached));
    } catch {}
    loadDay();
    loadCalendar(calYear, calMonth);
  }, []);

  // Expose silent refresh for native shell (iOS WebView) to call after sync
  useEffect(() => {
    (window as any).__refreshData = () => {
      loadDay(selectedDate);
      loadCalendar(calYear, calMonth);
    };
  });

  if (error) return (
    <main className="min-h-screen flex items-center justify-center bg-[#141414]">
      <p className="text-white/40 text-sm">ยังไม่ได้เชื่อมต่อ backend</p>
    </main>
  );

  if (!data) return (
    <main className="min-h-screen flex items-center justify-center bg-[#141414]">
      <div className="text-white/40 text-lg">กำลังโหลด...</div>
    </main>
  );

  const { signals } = data;
  const sleepPct = signals.sleep.hours
    ? Math.min(100, Math.round((signals.sleep.hours / 8) * 100))
    : null;

  return (
    <main className="min-h-screen pb-16 relative" style={{
      background: '#141414',
    }}>
      {/* Header */}
      <header className="px-6 pt-4 pb-3 animate-fade-up">
        <button onClick={() => setShowCal(!showCal)} className="flex items-center gap-2 w-full">
          <h1 className="text-[22px] font-semibold tracking-tight">
            วัน{data.day_th}ที่ {parseInt(data.date.split('-')[2])} {
              ['','ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.','ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.'][parseInt(data.date.split('-')[1])]
            }
          </h1>
          <span className="text-white/30 text-sm">{showCal ? '▲' : '▼'}</span>
        </button>
      </header>

      {/* Calendar */}
      {showCal && (
        <div className="mx-5 mb-4 glass-card p-4 animate-fade-up">
          {/* Month header with arrows */}
          <div className="flex items-center justify-between mb-3">
            <button onClick={prevMonth} className="text-white/50 px-3 py-1 text-lg">‹</button>
            <span className="text-sm font-semibold">
              {calData?.month_th || ''} {calYear + 543}
            </span>
            <button onClick={nextMonth} className="text-white/50 px-3 py-1 text-lg">›</button>
          </div>

          {/* Day headers — Sun first */}
          <div className="grid grid-cols-7 gap-1 text-center mb-1">
            {['อา','จ','อ','พ','พฤ','ศ','ส'].map(d => (
              <span key={d} className="text-[10px] text-white/30">{d}</span>
            ))}
          </div>

          {/* Days grid */}
          <div className="grid grid-cols-7 gap-1 text-center">
            {(() => {
              if (!calData) return <div className="col-span-7 text-center text-white/30 text-sm py-4">กำลังโหลด...</div>;
              // first_weekday: 0=Mon, convert to Sun-start: (fw + 1) % 7
              const blanks = Array.from(
                { length: (calData.first_weekday + 1) % 7 },
                (_, i) => <div key={`b${i}`} />
              );
              const colors: Record<string, string> = {
                green: '#30D158', yellow: '#FF9F0A', red: '#FF453A',
              };
              const days = calData.days.map((day) => {
                const d = parseInt(day.date.split('-')[2]);
                const isSelected = day.date === (selectedDate || data.date);
                const isFuture = day.score === null;
                return (
                  <button
                    key={day.date}
                    disabled={isFuture}
                    onClick={() => {
                      if (isFuture) return;
                      setSelectedDate(day.date);
                      loadDay(day.date);
                      setShowCal(false);
                    }}
                    className="flex flex-col items-center py-1.5 rounded-xl transition-all"
                    style={{
                      background: isSelected ? 'rgba(255,255,255,0.1)' : 'transparent',
                      opacity: isFuture ? 0.2 : 1,
                    }}
                  >
                    <div className="w-5 h-5 rounded-full border-2 mb-0.5" style={{
                      borderColor: isFuture ? '#333' : (colors[day.color] || '#333'),
                      background: day.has_workout && !isFuture ? (colors[day.color] || '#333') + '30' : 'transparent',
                    }} />
                    <span className="text-[11px]" style={{
                      color: isSelected ? '#fff' : 'rgba(255,255,255,0.5)',
                    }}>{d}</span>
                  </button>
                );
              });
              return [...blanks, ...days];
            })()}
          </div>

          {/* Back to today */}
          {selectedDate && (
            <button
              onClick={() => {
                setSelectedDate(undefined);
                loadDay();
                setShowCal(false);
                const now = new Date();
                setCalYear(now.getFullYear()); setCalMonth(now.getMonth() + 1);
                loadCalendar(now.getFullYear(), now.getMonth() + 1);
              }}
              className="mt-3 text-sm text-center w-full py-2" style={{ color: '#30D158' }}
            >
              กลับวันนี้
            </button>
          )}
        </div>
      )}

      {/* Widget pills */}
      <div className="flex gap-2 px-5 mb-5 animate-fade-up animate-delay-1">
        <div className="flex-1 glass-pill flex items-center justify-center gap-1.5 py-2">
          <span className="text-xs">📍</span>
          <span className="text-sm text-white/50">กรุงเทพ</span>
        </div>
        <div className="flex-1 glass-pill flex items-center justify-center gap-1.5 py-2">
          <span className="text-xs">
            {data.weather?.weather === 'ท้องฟ้าแจ่มใส' ? '☀️'
              : data.weather?.weather === 'มีเมฆบ้าง' ? '⛅'
              : data.weather?.weather?.includes('ฝน') ? '🌧'
              : data.weather?.weather?.includes('พายุ') ? '⛈' : '🌤'}
          </span>
          <span className="text-sm text-white/50">{data.weather?.temp ?? '—'}°C</span>
        </div>
        {(() => {
          const pm = data.weather?.pm25 ?? 0;
          const dotColor = pm <= 25 ? '#30D158' : pm <= 50 ? '#FFD60A' : pm <= 100 ? '#FF9F0A' : pm <= 200 ? '#FF453A' : '#BF5AF2';
          return (
            <div className="flex-1 glass-pill flex items-center justify-center gap-1.5 py-2">
              <div className="w-[6px] h-[6px] rounded-full" style={{ background: dotColor, boxShadow: `0 0 6px ${dotColor}` }} />
              <span className="text-sm text-white/50">PM {data.weather?.pm25 ?? '—'}</span>
            </div>
          );
        })()}
      </div>

      {/* Score + 3 metrics */}
      <div className="mx-5 mb-4 animate-fade-up animate-delay-2 rounded-[24px] p-5 flex items-center gap-5"
        style={{
          background: 'linear-gradient(160deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.02) 100%)',
          border: '1px solid rgba(255,255,255,0.1)',
          borderBottom: '1px solid rgba(0,0,0,0.3)',
          borderRight: '1px solid rgba(0,0,0,0.2)',
          boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.08), 0 12px 40px rgba(0,0,0,0.4), 4px 8px 20px rgba(0,0,0,0.3)',
        }}
      >
        <ScoreRing score={data.readiness} color={data.color} size={140} label={scoreLabel(data)} />
        <div className="flex-1 space-y-4">
          <MiniMetric label="ความเหนื่อยล้า" value={data.strain.score}
            color={data.strain.score <= 40 ? '#30D158' : data.strain.score <= 60 ? '#FF9F0A' : '#FF453A'}
            zone={[20, 40]} />
          <MiniMetric label="การฟื้นตัว" value={data.recovery.score ? Math.round(data.recovery.score) : null}
            color={(data.recovery.score ?? 0) >= 67 ? '#30D158' : (data.recovery.score ?? 0) >= 34 ? '#FF9F0A' : '#FF453A'}
            zone={[67, 100]} />
          <MiniMetric label="การนอน" value={sleepPct}
            color={(sleepPct ?? 0) >= 75 ? '#30D158' : (sleepPct ?? 0) >= 50 ? '#FF9F0A' : '#FF453A'}
            zone={[75, 100]} />
        </div>
      </div>

      {/* Illness banner — only when confidence is medium or high.
          Low = single noisy signal, not worth alarming.
          Anti-engagement ok here: this IS the edge-case alert exception. */}
      {data.illness && (data.illness.confidence === 'medium' || data.illness.confidence === 'high') && (
        <div className="mx-5 mb-4 animate-fade-up animate-delay-2 rounded-[18px] p-4"
          style={{
            background: data.illness.confidence === 'high'
              ? 'linear-gradient(135deg, rgba(255,69,58,0.12), rgba(255,69,58,0.04))'
              : 'linear-gradient(135deg, rgba(255,159,10,0.10), rgba(255,159,10,0.04))',
            border: `1px solid ${data.illness.confidence === 'high' ? 'rgba(255,69,58,0.35)' : 'rgba(255,159,10,0.3)'}`,
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <span className="text-base">{data.illness.confidence === 'high' ? '🛑' : '⚠️'}</span>
            <span className="text-[12px] uppercase tracking-[0.15em] font-semibold"
              style={{ color: data.illness.confidence === 'high' ? '#FF453A' : '#FF9F0A' }}>
              สัญญาณร่างกาย
            </span>
          </div>
          <p className="text-[15px] font-medium text-white mb-2">{data.illness.headline}</p>
          <ul className="space-y-1 text-[13px] text-white/70">
            {data.illness.signals.map((s, i) => (
              <li key={i}>· {s.msg}</li>
            ))}
            {data.illness.sustained && (
              <li className="text-white/80 italic">· ต่อเนื่องจากเมื่อวานแล้ว</li>
            )}
          </ul>
        </div>
      )}

      {/* AI Narration */}
      {data.reason && (() => {
        const ringColor = COLORS[data.color]?.ring || '#FF9F0A';
        return (
          <div className="mx-5 mb-4 animate-fade-up animate-delay-3 rounded-[20px] p-4 relative overflow-hidden"
            style={{
              background: 'rgba(255,255,255,0.04)',
              border: `1px solid ${ringColor}15`,
              boxShadow: `0 8px 32px rgba(0,0,0,0.3)`,
            }}
          >
            {/* Top glow — bright center, fading to sides */}
            <div className="absolute top-0 left-1/2 -translate-x-1/2 h-[1px] w-full" style={{
              background: `radial-gradient(ellipse at center, ${ringColor}90, ${ringColor}30 30%, transparent 70%)`,
            }} />
            <div className="absolute top-0 left-1/2 -translate-x-1/2 h-12 w-full" style={{
              background: `radial-gradient(ellipse at top, ${ringColor}10, transparent 70%)`,
            }} />
            <div className="flex items-center gap-1.5 mb-2.5">
              <div className="w-[6px] h-[6px] rounded-full" style={{ background: ringColor, boxShadow: `0 0 6px ${ringColor}80` }} />
              <span className="text-[12px] uppercase tracking-[0.15em] text-white/30">AI Summary</span>
            </div>
            <p className="text-base text-white leading-[1.8]">{data.reason}</p>
          </div>
        );
      })()}

      {/* Recommend for you — data-driven options (active: collapsed by default) */}
      {data.tips && data.tips.length > 0 && (
        <div className="mx-5 mb-4 animate-fade-up animate-delay-3">
          <button
            onClick={() => setShowTips(!showTips)}
            className="w-full rounded-[18px] px-5 py-4 flex items-center justify-between"
            style={{
              background: 'rgba(10,132,255,0.10)',
              border: '1px solid rgba(10,132,255,0.25)',
              boxShadow: '0 4px 16px rgba(10,132,255,0.08)',
            }}
          >
            <div className="flex items-center gap-2.5">
              <span className="text-[15px] font-semibold" style={{ color: '#5AC8FA' }}>แนะนำสำหรับวันนี้</span>
              <span className="text-[12px] px-2 py-0.5 rounded-full tabular-nums font-medium" style={{
                background: 'rgba(10,132,255,0.2)',
                color: '#5AC8FA',
              }}>
                {data.tips.length}
              </span>
            </div>
            <span className="text-base" style={{ color: 'rgba(90,200,250,0.5)' }}>{showTips ? '▲' : '▼'}</span>
          </button>

          {showTips && (
            <div className="mt-2.5 space-y-2.5 animate-fade-up">
              {data.tips.map((tip, i) => (
                <div key={i} className="rounded-[16px] p-4" style={{
                  background: 'rgba(10,132,255,0.06)',
                  border: '1px solid rgba(10,132,255,0.15)',
                }}>
                  <div className="text-[15px] font-semibold mb-2.5 leading-[1.5]" style={{ color: '#7FD4FF' }}>{tip.headline}</div>
                  <ul className="space-y-2">
                    {tip.options.map((opt, j) => (
                      <li key={j} className="text-[14px] leading-[1.65] flex gap-2.5" style={{ color: 'rgba(255,255,255,0.78)' }}>
                        <span className="shrink-0 mt-px" style={{ color: '#5AC8FA' }}>•</span>
                        <span>{opt}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
              <div className="text-[12px] text-center pt-1.5 pb-1" style={{ color: 'rgba(90,200,250,0.45)' }}>
                {data.tips_personalized
                  ? 'ผลการแนะนำมาจากการวิเคราะห์สิ่งที่คุณเคยทำในช่วงที่ผ่านมา'
                  : 'คำแนะนำทั่วไป — จะวิเคราะห์เฉพาะคุณเมื่อมีข้อมูลมากพอ'}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Stress card — chart-as-hero (Bevel-style today's stress chart).
          Dropped: 3 numbers (Highest/Lowest/Average) and circular gauge.
          Per Jig: "min max avg ผมเฉยๆ ดูจากกราฟก็ได้". The chart conveys
          everything at a glance — trend, peaks, sleep band, and the
          rightmost point shows current/last state.
          Anti-engagement framing intact: chart is a day-story, not a
          live gauge inviting obsessive refreshing. */}
      {data.stress && (() => {
        const s = data.stress;
        // Empty-day flag — no stress samples at all (e.g., watch wasn't
        // worn that day). Card still renders so user knows the day was
        // measured, but chart and value show "no data" instead of being
        // silently hidden (which left users wondering "ทำไมไม่มีอะไร?").
        const noData = s.current === null;

        // Live-day check — stale/watch-off detection only applies when
        // viewing TODAY. For past-date views (calendar pick), the data
        // is historical fact: "ไม่ได้สวมนาฬิกา" makes no sense for a
        // day 2 days ago, and the last sample is just the day's last
        // reading (not "stale"). Comparing past samples to `Date.now()`
        // would always trigger stale/watchOff, hiding the chart dot
        // and labeling every history view as "watch off."
        // Use LOCAL date (not UTC) — `data.date` is set by backend in
        // local time, and toISOString() in early-morning Bangkok would
        // return yesterday's UTC date, breaking the comparison.
        const now = new Date();
        const todayStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
        const isLive = data.date === todayStr;

        // Sample-level freshness — only meaningful for live view.
        let updatedLabel = '';
        let stale = false;
        if (s.latest_sample_time) {
          const d = new Date(s.latest_sample_time);
          updatedLabel = `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
          stale = isLive && (Date.now() - d.getTime()) / 60000 > 60;
        }

        // Watch-worn detection — uses HR (dense ~every 6 min when worn),
        // not HRV (sparse ~every 1-3 hr). >30 min stale HR = watch off.
        // Skip entirely for past-date views (see isLive above).
        const watchOff = (() => {
          if (!isLive) return false;
          if (!s.latest_hr_sample_time) return true;
          const d = new Date(s.latest_hr_sample_time);
          return (Date.now() - d.getTime()) / 60000 > 30;
        })();
        const lastHrLabel = s.latest_hr_sample_time
          ? (() => {
              const d = new Date(s.latest_hr_sample_time);
              return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
            })()
          : null;

        // Chart geometry — smooth gradient line, hourly aggregation.
        // Per Jig: line chart with color was the right call (bars rejected).
        // Hourly aggregation (vs per-sample 175 pts) keeps the line smooth
        // and Bevel-like without per-sample noise. X-axis auto-scales to
        // the data range so the line always fills the chart width.
        const chartW = 320, chartH = 70;
        const padL = 6, padR = 14, padT = 5, padB = 14;
        const innerW = chartW - padL - padR;
        const innerH = chartH - padT - padB;
        const yToSvg = (stress: number) => padT + (1 - stress / 100) * innerH;

        // cycle_start anchors x=0. Fall back to yesterday-22:00.
        const cycleStart = s.cycle_start
          ? new Date(s.cycle_start)
          : (() => {
              const d = new Date();
              d.setHours(22, 0, 0, 0);
              d.setDate(d.getDate() - 1);
              return d;
            })();
        const minsFromCycleStart = (iso: string) => {
          const d = new Date(iso);
          return (d.getTime() - cycleStart.getTime()) / 60000;
        };

        // X-axis LOCKED to 24h cycle (per Jig "สาบานว่าครบ 24 ชม.").
        const TOTAL_HOURS = 24;
        const xForHour = (h: number) => padL + (h / TOTAL_HOURS) * innerW;

        // Hourly aggregation — average stress per hour-from-cycle-start.
        // Per Jig (multiple times): "ทำเป็น hourly ก็พอ ทำไมต้องถี่ๆๆ"
        // — per-sample (175 pts) was too noisy. 24 buckets, smooth line.
        const hourlyBuckets: { sum: number; count: number }[] =
          Array.from({ length: TOTAL_HOURS }, () => ({ sum: 0, count: 0 }));
        for (const pt of (s.timeline || [])) {
          const m = minsFromCycleStart(pt.time);
          if (m < 0 || m >= TOTAL_HOURS * 60) continue;
          const h = Math.floor(m / 60);
          hourlyBuckets[h].sum += pt.stress;
          hourlyBuckets[h].count++;
        }

        // Break into segments at empty hours — Bevel leaves visible
        // gaps when the watch was off (see user's IMG_1013/1014). Each
        // segment = a run of consecutive hours that have data.
        const segments: { hour: number; stress: number }[][] = [];
        {
          let cur: { hour: number; stress: number }[] = [];
          for (let h = 0; h < TOTAL_HOURS; h++) {
            if (hourlyBuckets[h].count > 0) {
              cur.push({ hour: h, stress: Math.round(hourlyBuckets[h].sum / hourlyBuckets[h].count) });
            } else if (cur.length > 0) {
              segments.push(cur);
              cur = [];
            }
          }
          if (cur.length > 0) segments.push(cur);
        }

        // For each segment, build a smooth bezier line. Bevel-style: no
        // area fill (Jig: "เอาออกดีกว่า Bevel เขาก็ไม่มี") — just the line.
        const segmentPaths = segments.map(seg => {
          const pts = seg.map(p => ({ x: xForHour(p.hour + 0.5), y: yToSvg(p.stress) }));
          if (pts.length === 0) return { line: '' };
          if (pts.length === 1) {
            return { line: `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}` };
          }
          let line = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`;
          for (let i = 1; i < pts.length - 1; i++) {
            const cur = pts[i];
            const next = pts[i + 1];
            const midX = (cur.x + next.x) / 2;
            const midY = (cur.y + next.y) / 2;
            line += ` Q ${cur.x.toFixed(1)} ${cur.y.toFixed(1)} ${midX.toFixed(1)} ${midY.toFixed(1)}`;
          }
          const last = pts[pts.length - 1];
          line += ` T ${last.x.toFixed(1)} ${last.y.toFixed(1)}`;
          return { line };
        });

        // Sleep band — cycle_start → wakeup, mapped to hour x-positions.
        let sleepBand: { x: number; w: number } | null = null;
        const wakeup = data.sleep?.wakeup;
        if (wakeup) {
          const [wh, wm] = wakeup.split(':').map(Number);
          const wakeupDt = new Date(cycleStart);
          wakeupDt.setHours(wh, wm, 0, 0);
          if (wakeupDt < cycleStart) wakeupDt.setDate(wakeupDt.getDate() + 1);
          const wakeupHours = (wakeupDt.getTime() - cycleStart.getTime()) / 3600_000;
          if (wakeupHours > 0 && wakeupHours <= TOTAL_HOURS) {
            sleepBand = { x: padL, w: xForHour(wakeupHours) - padL };
          }
        }

        // Workout markers — Bevel-style 🏋️ icon above the chart at each
        // workout's start time. `time` from backend is "HH:MM" so we
        // combine with the cycle's calendar day to build a datetime.
        // Merge workouts whose end-to-start gap is within MERGE_GAP_H —
        // two morning workouts back-to-back (e.g., weights then yoga
        // within 1h) read as one "session." Workouts >1h apart stay
        // as separate blocks. Time-based threshold (not pixel-based)
        // so it survives chart-width changes.
        const MERGE_GAP_H = 1;
        const rawWorkouts = (data.strain?.workouts || [])
          .map(w => {
            if (!w.time) return null;
            const [hh, mm] = w.time.split(':').map(Number);
            if (Number.isNaN(hh)) return null;
            const wDt = new Date(cycleStart);
            wDt.setHours(hh, mm || 0, 0, 0);
            if (wDt < cycleStart) wDt.setDate(wDt.getDate() + 1);
            const startH = (wDt.getTime() - cycleStart.getTime()) / 3600_000;
            if (startH < 0 || startH > TOTAL_HOURS) return null;
            const endH = Math.min(TOTAL_HOURS, startH + (w.duration_min || 30) / 60);
            return { startH, endH };
          })
          .filter((w): w is { startH: number; endH: number } => w !== null)
          .sort((a, b) => a.startH - b.startH);
        const mergedSessions: { startH: number; endH: number }[] = [];
        for (const w of rawWorkouts) {
          const last = mergedSessions[mergedSessions.length - 1];
          if (last && w.startH <= last.endH + MERGE_GAP_H) {
            last.endH = Math.max(last.endH, w.endH);
          } else {
            mergedSessions.push({ startH: w.startH, endH: w.endH });
          }
        }
        const workoutMarkers = mergedSessions.map(s => ({
          x: xForHour(s.startH),
          w: xForHour(s.endH) - xForHour(s.startH),
        }));

        // Time-axis labels every 4h (per Jig's "4 8 12") — round clock
        // hours within the 24h cycle window. With cycle_start typically
        // late-evening, this lands labels like 04:00 / 08:00 / 12:00 /
        // 16:00 / 20:00 (5 evenly-spaced labels across the day).
        const timeLabels: { x: number; label: string }[] = (() => {
          const out: { x: number; label: string }[] = [];
          for (const hour of [4, 8, 12, 16, 20]) {
            const candidate = new Date(cycleStart);
            candidate.setHours(hour, 0, 0, 0);
            // If the candidate clock-hour lands BEFORE cycle_start
            // (e.g., cycle started 22:00 yesterday, label "04:00" is
            // tomorrow morning) bump to next day.
            if (candidate < cycleStart) candidate.setDate(candidate.getDate() + 1);
            const hoursFromStart = (candidate.getTime() - cycleStart.getTime()) / 3600_000;
            if (hoursFromStart <= 0 || hoursFromStart >= TOTAL_HOURS) continue;
            out.push({
              x: xForHour(hoursFromStart),
              label: `${String(hour).padStart(2,'0')}:00`,
            });
          }
          return out;
        })();

        // Color helper + current value (null-safe for empty days)
        const colorForStress = (stress: number) =>
          stress >= 70 ? '#FF453A' : stress >= 40 ? '#FF9F0A' : '#30D158';
        const curVal = s.current;
        const curColor = curVal === null ? '#888' : colorForStress(curVal);

        return (
          <div className="mx-5 mb-4 animate-fade-up animate-delay-4">
            <div className="glass-card px-4 pt-[6px] pb-2">
              {/* Title row — title left, big current value right */}
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[14px] font-semibold text-white">ความเครียดวันนี้</span>
                <span className="text-[22px] tabular-nums font-semibold leading-none shrink-0"
                      style={{ color: noData || watchOff || curVal === null
                        ? 'rgba(255,255,255,0.3)'
                        : (stale ? '#888' : curColor) }}>
                  {noData || watchOff || curVal === null ? '—' : curVal}
                </span>
              </div>

              {/* Today's stress chart — Bevel-style:
                  - Smooth gradient line through 24 hourly points (avg)
                  - Area fill below for visual weight
                  - Sleep band overlay (slate-blue + 🌙)
                  - Y-axis labels 25/50/75/100, time labels every 6h
                  - X-axis auto-scales to data so the line fills the chart */}
              <svg width="100%" height={chartH} viewBox={`0 0 ${chartW} ${chartH}`}
                   preserveAspectRatio="none" className="mt-2 block">
                <defs>
                  <linearGradient id="stressLineGrad" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%"  stopColor="#FF453A" />
                    <stop offset="50%" stopColor="#FF9F0A" />
                    <stop offset="100%" stopColor="#30D158" />
                  </linearGradient>
                </defs>

                {/* Y-axis grid lines at 25/50/75 (subtle reference) */}
                {[25, 50, 75].map(y => (
                  <line key={y} x1={padL} x2={chartW - padR}
                        y1={yToSvg(y)} y2={yToSvg(y)}
                        stroke="rgba(255,255,255,0.05)" strokeDasharray="2,3" />
                ))}

                {/* Sleep band */}
                {sleepBand && sleepBand.w > 0 && (
                  <rect x={sleepBand.x} y={padT} width={sleepBand.w} height={innerH}
                        fill="rgba(100,140,220,0.16)" rx="2" />
                )}

                {/* Workout duration bands — orange-tinted vertical strip
                    spanning the workout time, like Bevel's chart. The
                    🏋️ icon sits on top above the chart area. */}
                {workoutMarkers.map((wm, i) => (
                  <rect key={`wb${i}`} x={wm.x} y={padT}
                        width={Math.max(2, wm.w)} height={innerH}
                        fill="rgba(255,159,10,0.07)" rx="2" />
                ))}

                {/* Stress lines — one per data segment. Bevel-style: gaps
                    between segments stay empty so "watch was off" reads
                    visually. Non-scaling stroke for consistent width. */}
                {segmentPaths.map((sp, i) => sp.line && (
                  <path key={`l${i}`} d={sp.line} stroke="url(#stressLineGrad)"
                        strokeWidth="1.2" fill="none"
                        strokeLinejoin="round" strokeLinecap="round"
                        vectorEffect="non-scaling-stroke" />
                ))}

                {/* Moon icon over sleep band */}
                {sleepBand && sleepBand.w > 24 && (
                  <text x={sleepBand.x + sleepBand.w / 2} y={padT + 11}
                        textAnchor="middle" fontSize="11" opacity="0.75">🌙</text>
                )}

                {/* Workout 🏋️ icon — at top of each workout's start position */}
                {workoutMarkers.map((wm, i) => (
                  <text key={`wi${i}`} x={wm.x + Math.max(2, wm.w) / 2} y={padT + 9}
                        textAnchor="middle" fontSize="10" opacity="0.85">🏋️</text>
                ))}

                {/* Y-axis labels (right edge) */}
                {[25, 50, 75, 100].map(y => (
                  <text key={y} x={chartW - padR + 1} y={yToSvg(y) + 3}
                        fontSize="7" fill="rgba(255,255,255,0.25)"
                        textAnchor="start">{y}</text>
                ))}

                {/* Time-axis labels — auto-positioned, snapped to round hours */}
                {timeLabels.map(t => (
                  <text key={t.label} x={t.x} y={chartH - 4} fontSize="9"
                        fill="rgba(255,255,255,0.3)" textAnchor="middle">{t.label}</text>
                ))}
              </svg>
            </div>
          </div>
        );
      })()}

      {/* Health Monitor — Bevel-style grid */}
      <div className="mx-5 mb-4 animate-fade-up animate-delay-4">
        <p className="text-[12px] uppercase tracking-[0.15em] text-white/30 mb-2 px-1">Health Monitor</p>
        <div className="grid grid-cols-2 gap-2">
          <MonitorCard icon={<IconHeart />} label="RHR" value={signals.rhr.value} unit="bpm"
            status={signals.rhr.status} baseline={signals.rhr.baseline} />
          <MonitorCard icon={<IconWave />} label="HRV" value={signals.hrv.value} unit="ms"
            status={signals.hrv.status} baseline={signals.hrv.baseline} />
          <MonitorCard icon={<IconLung />} label="RR" value={data.vitals?.rr ?? null} unit="rpm"
            status={data.vitals?.rr ? (data.vitals.rr >= 10 && data.vitals.rr <= 20 ? 'good' : 'warning') : 'no_data'} />
          <MonitorCard icon={<IconO2 />} label="SpO2" value={data.vitals?.spo2 ?? null} unit="%"
            status={data.vitals?.spo2 ? (data.vitals.spo2 >= 95 ? 'good' : data.vitals.spo2 >= 90 ? 'warning' : 'bad') : 'no_data'} />
          <MonitorCard icon={<IconMoon />} label="การนอน" value={signals.sleep.hours} unit="ชม."
            status={signals.sleep.hours == null ? 'no_data' : signals.sleep.hours >= 7 ? 'good' : signals.sleep.hours >= 6 ? 'normal' : 'warning'} />
          <MonitorCard icon={<IconSteps />} label="ก้าววันนี้" value={data.strain.steps} unit="ก้าว"
            status="normal" format={(v) => v.toLocaleString()} />
        </div>
      </div>

      {/* Timeline */}
      {data.strain.workouts.length > 0 && (
        <div className="mx-5 mb-4 animate-fade-up animate-delay-5">
          <p className="text-[12px] uppercase tracking-[0.15em] text-white/30 mb-2 px-1">Activities</p>
          <div className="glass-card px-4 py-2">
            {data.strain.workouts.map((w, i) => (
              <div key={i} className="flex gap-3">
                {/* Timeline line + dot */}
                <div className="flex flex-col items-center w-4 pt-4">
                  <div className="w-2.5 h-2.5 rounded-full border-2 shrink-0" style={{
                    borderColor: 'rgba(255,159,10,0.6)',
                    background: i === 0 ? 'rgba(255,159,10,0.6)' : 'transparent',
                  }} />
                  {i < data.strain.workouts.length - 1 && (
                    <div className="w-[1px] flex-1" style={{ background: 'rgba(255,255,255,0.08)' }} />
                  )}
                </div>
                {/* Content */}
                <div className="flex-1 flex items-center justify-between py-3">
                  <div>
                    <p className="text-sm font-medium text-white/80">{WK[w.type] || w.type}</p>
                    <p className="text-[12px] text-white/30">{w.time || '—'} · {w.duration_min} นาที</p>
                  </div>
                  <span className="text-base font-semibold text-white/90">{w.kcal} <span className="text-[11px] font-normal text-white/30">kcal</span></span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tip — disabled, AI summary covers this */}
    </main>
  );
}
