'use client';

import { useEffect, useState } from 'react';
import { api, DailyStatus, TimelineEvent, YearlySummary, ZoneRow } from '@/lib/api';
import { TodayCard } from '@/components/TodayCard';
import { DayStrip } from '@/components/DayStrip';
import { MonthHeatmap } from '@/components/MonthHeatmap';
import { NormsCard } from '@/components/NormsCard';
import { UnifiedTimeline } from '@/components/UnifiedTimeline';
import { ZoneBar } from '@/components/ZoneBar';
import { YearlyCards } from '@/components/YearlyCards';
import { PolarizationCard } from '@/components/PolarizationCard';

type Data = {
  daily: DailyStatus;
  timeline: TimelineEvent[];
  yearly: YearlySummary[];
  zones: ZoneRow[];
  polar: { bucket: string; samples: number; pct: number }[];
  maxHr: number;
};

export default function Dashboard() {
  const [data, setData] = useState<Data | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState(false);
  const [selected, setSelected] = useState<TimelineEvent | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [daily, timeline, yearly, zones] = await Promise.all([
          api.dailyStatus(30),
          api.unifiedTimeline(),
          api.yearly(),
          api.zones(),
        ]);
        setData({
          daily,
          timeline,
          yearly: yearly.yearly,
          zones: zones.by_sport,
          polar: zones.polarization_365d,
          maxHr: zones.max_hr,
        });
      } catch (e: any) {
        setErr(e.message || String(e));
      }
    })();
  }, []);

  if (err) {
    return (
      <main className="max-w-4xl mx-auto p-6">
        <h1 className="text-2xl mb-4">smart_health</h1>
        <div className="bg-panel border border-bad rounded p-4 text-bad text-sm">
          <div className="font-medium">Backend unreachable</div>
          <div className="text-gray-400 mt-2">{err}</div>
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="max-w-4xl mx-auto p-6">
        <h1 className="text-2xl mb-4">smart_health</h1>
        <div className="text-gray-500 text-sm">Loading…</div>
      </main>
    );
  }

  const last7 = data.daily.days.slice(-7);
  const last30 = data.daily.days;

  const summary = summarize(last30);

  return (
    <main className="max-w-4xl mx-auto p-6 space-y-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">smart_health</h1>
        <div className="flex items-center gap-4">
          <a
            href="/journal"
            className="text-xs text-accent hover:brightness-110 underline"
          >
            Journal
          </a>
          <button
            onClick={() => setShowDetails((v) => !v)}
            className="text-xs text-gray-500 hover:text-gray-300 underline"
          >
            {showDetails ? 'ซ่อน' : 'ดู'} details & charts
          </button>
        </div>
      </header>

      <TodayCard day={data.daily.today} />

      <DayStrip days={last7} title="7 วันที่ผ่านมา" />

      <MonthHeatmap days={last30} />

      <NormsCard norms={data.daily.personal_norms} />

      <MonthSummaryCard summary={summary} />

      {showDetails && (
        <div className="space-y-4 pt-4 border-t border-border">
          <div className="text-xs uppercase tracking-wider text-gray-500">
            รายละเอียดเพิ่มเติม
          </div>

          <UnifiedTimeline events={data.timeline} onSelect={setSelected} />

          {selected && (
            <div className="bg-panel border border-accent rounded p-3 text-sm">
              <div className="flex items-baseline justify-between">
                <div className="font-medium text-gray-200">{selected.label}</div>
                <button
                  onClick={() => setSelected(null)}
                  className="text-xs text-gray-500 hover:text-gray-300"
                >
                  close
                </button>
              </div>
              <div className="text-xs text-gray-500 mt-1">
                {selected.kind} · {selected.start} → {selected.end} ·{' '}
                {selected.days}d · {selected.severity}
              </div>
            </div>
          )}

          <YearlyCards years={data.yearly} />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ZoneBar rows={data.zones} maxHr={data.maxHr} />
            <PolarizationCard buckets={data.polar} />
          </div>
        </div>
      )}
    </main>
  );
}

function summarize(days: { status: string }[]) {
  const counts = { normal: 0, warning: 0, bad: 0, no_data: 0, no_signal: 0 };
  for (const d of days) {
    counts[d.status as keyof typeof counts] =
      (counts[d.status as keyof typeof counts] || 0) + 1;
  }
  const worn = days.length - counts.no_data - counts.no_signal;
  return { ...counts, worn, total: days.length };
}

function MonthSummaryCard({
  summary,
}: {
  summary: {
    normal: number;
    warning: number;
    bad: number;
    no_data: number;
    no_signal: number;
    worn: number;
    total: number;
  };
}) {
  const wornPct = summary.total > 0 ? (summary.worn / summary.total) * 100 : 0;
  const normalPct = summary.worn > 0 ? (summary.normal / summary.worn) * 100 : 0;

  let verdict = '';
  if (normalPct >= 80) verdict = '🟢 เดือนนี้ร่างกายคุณโอเคมาก';
  else if (normalPct >= 60) verdict = '🟡 เดือนนี้มีวันที่ระวังบ้าง แต่โดยรวมโอเค';
  else if (normalPct >= 40) verdict = '🟠 เดือนนี้มีสัญญาณไม่ปกติค่อนข้างบ่อย';
  else verdict = '🔴 เดือนนี้ร่างกายส่งสัญญาณผิดปกติบ่อย ควรดูแลเป็นพิเศษ';

  return (
    <div className="bg-panel border border-border rounded-lg p-4">
      <div className="text-sm text-gray-300 font-medium mb-3">สรุป 30 วัน</div>
      <div className="text-lg text-gray-100 mb-3">{verdict}</div>
      <div className="grid grid-cols-4 gap-2 text-sm">
        <SummaryStat label="ปกติ" value={summary.normal} color="#5be49b" />
        <SummaryStat label="ระวัง" value={summary.warning} color="#f7b955" />
        <SummaryStat label="ไม่ปกติ" value={summary.bad} color="#ef5350" />
        <SummaryStat
          label="ไม่ได้ใส่"
          value={summary.no_data + summary.no_signal}
          color="#64748b"
        />
      </div>
      <div className="text-xs text-gray-500 mt-3">
        ใส่ Watch {summary.worn}/{summary.total} วัน ({wornPct.toFixed(0)}%) · มีสัญญาณปกติ{' '}
        {normalPct.toFixed(0)}% ของวันที่ใส่
      </div>
    </div>
  );
}

function SummaryStat({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="bg-bg/50 border border-border rounded p-2 text-center">
      <div className="text-2xl font-semibold" style={{ color }}>
        {value}
      </div>
      <div className="text-xs text-gray-500 mt-1">{label}</div>
    </div>
  );
}
