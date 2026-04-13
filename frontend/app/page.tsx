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
        <span className="font-extralight" style={{
          fontSize: size * 0.32, color: c.main,
          textShadow: `0 0 20px ${c.glow}`,
        }}>{score}</span>
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
        <span className="text-[15px] text-white/50">{label}</span>
        <span className="text-[15px] font-semibold" style={{ color }}>{value != null ? `${value}%` : '—'}</span>
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
          <MiniMetric label="ความเหนื่อย" value={data.strain.score} color="#FF9F0A" zone={[20, 40]} />
          <MiniMetric label="การฟื้นตัว" value={data.recovery.score ? Math.round(data.recovery.score) : null} color="#30D158" zone={[67, 100]} />
          <MiniMetric label="การนอน" value={sleepPct} color="#BF5AF2" zone={[75, 100]} />
        </div>
      </div>

      {/* AI Narration */}
      {data.reason && (
        <div className="mx-5 glass-card p-4 mb-4 animate-fade-up animate-delay-3">
          <div className="flex items-center gap-1.5 mb-2.5">
            <div className="w-[6px] h-[6px] rounded-full bg-purple-400" style={{ boxShadow: '0 0 6px rgba(167,139,250,0.5)' }} />
            <span className="text-[12px] uppercase tracking-[0.15em] text-white/30">AI Summary</span>
          </div>
          <p className="text-sm text-white/60 leading-[1.7]">{data.reason}</p>
        </div>
      )}

      {/* Signals */}
      <div className="mx-5 glass-card px-4 mb-4 divide-y divide-white/[0.04] animate-fade-up animate-delay-4">
        <SignalRow label="HRV" value={signals.hrv.value} baseline={signals.hrv.baseline} unit="ms" status={signals.hrv.status} />
        <SignalRow label="RHR" value={signals.rhr.value} baseline={signals.rhr.baseline} unit="bpm" status={signals.rhr.status} />
        <SignalRow label="การนอน" value={signals.sleep.hours} baseline={null} unit="ชม."
          status={signals.sleep.hours == null ? 'no_data' : signals.sleep.hours >= 7 ? 'good' : signals.sleep.hours >= 6 ? 'normal' : 'warning'}
          sub={signals.sleep.bedtime ? `เข้านอน ${signals.sleep.bedtime}` : undefined} />
      </div>

      {/* Workouts */}
      {data.strain.workouts.length > 0 && (
        <div className="mx-5 glass-card p-4 mb-4 animate-fade-up animate-delay-5">
          <p className="text-[12px] uppercase tracking-[0.15em] text-white/30 mb-3">กิจกรรมวันนี้</p>
          {data.strain.workouts.map((w, i) => (
            <div key={i} className="flex justify-between py-1.5">
              <span className="text-sm text-white/50">{WK[w.type] || w.type}</span>
              <span className="text-sm font-medium text-white/80">{w.duration_min} นาที</span>
            </div>
          ))}
          <div className="flex gap-4 mt-2 pt-2 border-t border-white/[0.04]">
            <span className="text-sm text-white/25">{data.strain.steps.toLocaleString()} ก้าว</span>
            <span className="text-sm text-white/25">{data.strain.active_kcal} kcal</span>
          </div>
        </div>
      )}

      {/* Tip */}
      {data.tip && (
        <div className="mx-5 glass-card p-4 animate-fade-up animate-delay-5">
          <p className="text-sm text-white/50 leading-[1.7]">{data.tip}</p>
        </div>
      )}
    </main>
  );
}
