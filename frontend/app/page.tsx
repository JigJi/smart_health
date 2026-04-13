'use client';

import { useEffect, useState } from 'react';
import { api, TodayData } from '@/lib/api';

/* ─── Score Ring with glow ─── */
function ScoreRing({ score, color, size = 160 }: {
  score: number;
  color: 'green' | 'yellow' | 'red';
  size?: number;
}) {
  const colors = {
    green: { main: '#30D158', glow: 'rgba(48,209,88,0.25)' },
    yellow: { main: '#FF9F0A', glow: 'rgba(255,159,10,0.25)' },
    red: { main: '#FF453A', glow: 'rgba(255,69,58,0.25)' },
  };
  const c = colors[color];
  const stroke = 7;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (score / 100) * circ;

  return (
    <div className="relative flex items-center justify-center">
      {/* Glow */}
      <div className="absolute ring-glow rounded-full" style={{
        width: size + 40, height: size + 40,
        background: `radial-gradient(circle, ${c.glow} 0%, transparent 70%)`,
      }} />
      <svg width={size} height={size} className="-rotate-90 relative z-10">
        {/* Track */}
        <circle cx={size/2} cy={size/2} r={r}
          fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={stroke} />
        {/* Progress */}
        <circle cx={size/2} cy={size/2} r={r}
          fill="none" stroke={c.main} strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circ} strokeDashoffset={offset}
          style={{
            transition: 'stroke-dashoffset 1.5s cubic-bezier(0.16,1,0.3,1)',
            filter: `drop-shadow(0 0 8px ${c.main})`,
          }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center z-20">
        <div className="flex items-baseline" style={{ color: c.main, textShadow: `0 0 20px ${c.glow}` }}>
          <span className="font-extralight" style={{ fontSize: size * 0.32 }}>{score}</span>
          <span className="font-light" style={{ fontSize: size * 0.14 }}>%</span>
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
        <span className="text-base text-white/50">{label}</span>
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
  TraditionalStrengthTraining: 'เวท', FunctionalStrengthTraining: 'Functional',
  Elliptical: 'เครื่องเดิน', Cycling: 'ปั่นจักรยาน', Boxing: 'มวย',
  CoreTraining: 'Core', HIIT: 'HIIT', CardioDance: 'เต้น',
  Walking: 'เดิน', Running: 'วิ่ง', Yoga: 'โยคะ',
  Swimming: 'ว่ายน้ำ', TableTennis: 'ปิงปอง',
};

/* ─── Main page ─── */
export default function Home() {
  const [data, setData] = useState<TodayData | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    api.today().then(setData).catch(() => setError(true));
  }, []);

  if (error) return (
    <main className="min-h-screen flex items-center justify-center bg-[#141414]">
      <p className="text-white/40 text-sm">ยังไม่ได้เชื่อมต่อ backend</p>
    </main>
  );

  if (!data) return (
    <main className="min-h-screen flex items-center justify-center bg-[#141414]">
      <div className="text-white/20 text-sm">กำลังโหลด...</div>
    </main>
  );

  const { signals } = data;
  const sleepPct = signals.sleep.hours
    ? Math.min(100, Math.round((signals.sleep.hours / 8) * 100))
    : null;

  return (
    <main className="min-h-screen pb-16" style={{
      background: '#141414',
    }}>
      {/* Header */}
      <header className="px-6 pt-4 pb-3 animate-fade-up">
        <h1 className="text-[22px] font-semibold tracking-tight">
          วัน{data.day_th}ที่ {parseInt(data.date.split('-')[2])} {
            ['','ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.','ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.'][parseInt(data.date.split('-')[1])]
          }
        </h1>
      </header>

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
      <div className="mx-5 glass-card-elevated p-5 flex items-center gap-5 mb-4 animate-fade-up animate-delay-2">
        <ScoreRing score={data.readiness} color={data.color} size={140} />
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

      {/* AI Narration */}
      {data.reason && (
        <div className="mx-5 glass-card p-4 mb-4 animate-fade-up animate-delay-3">
          <div className="flex items-center gap-1.5 mb-2.5">
            <div className="w-[6px] h-[6px] rounded-full bg-purple-400" style={{ boxShadow: '0 0 6px rgba(167,139,250,0.5)' }} />
            <span className="text-[12px] uppercase tracking-[0.15em] text-white/30">AI Summary</span>
          </div>
          <p className="text-base text-white/60 leading-[1.8]">{data.reason}</p>
        </div>
      )}

      {/* Health Monitor — Bevel-style grid */}
      <div className="mx-5 mb-4 animate-fade-up animate-delay-4">
        <p className="text-[12px] uppercase tracking-[0.15em] text-white/30 mb-2 px-1">Health Monitor</p>
        <div className="grid grid-cols-2 gap-2">
          <MonitorCard icon={<IconHeart />} label="RHR" value={signals.rhr.value} unit="bpm"
            status={signals.rhr.status} baseline={signals.rhr.baseline} />
          <MonitorCard icon={<IconWave />} label="HRV" value={signals.hrv.value} unit="ms"
            status={signals.hrv.status} baseline={signals.hrv.baseline} />
          <MonitorCard icon={<IconLung />} label="RR" value={data.vitals?.rr ?? null} unit="rpm"
            status={data.vitals?.rr ? (data.vitals.rr >= 12 && data.vitals.rr <= 20 ? 'good' : 'warning') : 'no_data'} />
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
          <p className="text-[12px] uppercase tracking-[0.15em] text-white/30 mb-2 px-1">Timeline</p>
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
      {false && data.tip && (
        <div className="mx-5 glass-card p-4 animate-fade-up animate-delay-5">
          <p className="text-sm text-white/50 leading-[1.7]">{data.tip}</p>
        </div>
      )}
    </main>
  );
}
