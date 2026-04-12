'use client';

import { DayStatus } from '@/lib/api';

const STATUS_COLOR: Record<string, string> = {
  normal: '#5be49b',
  warning: '#f7b955',
  bad: '#ef5350',
  no_data: '#1f242e',
  no_signal: '#2a2f3a',
  low_confidence: '#334155',
};

const STATUS_LABEL_TH: Record<string, string> = {
  normal: 'ปกติ',
  warning: 'ระวัง',
  bad: 'ไม่ปกติ',
  no_data: 'ไม่ได้ใส่',
  no_signal: 'ไม่มี reading',
  low_confidence: 'ข้อมูลไม่พอ',
};

export function MonthHeatmap({ days }: { days: DayStatus[] }) {
  // Align to weekday grid: Sun=0..Sat=6
  if (days.length === 0) return null;
  const first = new Date(days[0].day);
  const leadingBlanks = first.getDay(); // 0 for Sun

  const cells: ({ kind: 'blank' } | { kind: 'day'; data: DayStatus })[] = [];
  for (let i = 0; i < leadingBlanks; i++) cells.push({ kind: 'blank' });
  for (const d of days) cells.push({ kind: 'day', data: d });

  const counts = days.reduce<Record<string, number>>((acc, d) => {
    acc[d.status] = (acc[d.status] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="bg-panel border border-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm text-gray-300 font-medium">30 วันล่าสุด</div>
        <div className="flex gap-3 text-xs">
          {(['normal', 'warning', 'bad', 'no_data'] as const).map((s) => (
            <span key={s} className="flex items-center gap-1">
              <span
                className="inline-block w-3 h-3 rounded"
                style={{ background: STATUS_COLOR[s] }}
              />
              <span className="text-gray-400">
                {STATUS_LABEL_TH[s]} {counts[s] ? `(${counts[s]})` : ''}
              </span>
            </span>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-7 gap-1">
        {['อา', 'จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส'].map((d) => (
          <div key={d} className="text-[10px] text-gray-500 text-center">
            {d}
          </div>
        ))}
        {cells.map((c, i) => {
          if (c.kind === 'blank') {
            return <div key={`b${i}`} />;
          }
          const d = c.data;
          const color = STATUS_COLOR[d.status];
          const isGrey = d.status === 'no_data' || d.status === 'no_signal' || d.status === 'low_confidence';
          return (
            <div
              key={d.day}
              className="aspect-square rounded flex items-center justify-center text-[10px] font-medium"
              style={{
                background: isGrey ? color : color,
                color: isGrey ? '#64748b' : '#0b0d12',
                opacity: isGrey ? 0.5 : 1,
              }}
              title={`${d.day} · ${STATUS_LABEL_TH[d.status]}${
                d.reasons_th[0] ? '\n' + d.reasons_th[0] : ''
              }`}
            >
              {d.day.slice(8, 10)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
