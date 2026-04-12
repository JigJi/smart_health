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

export function DayStrip({
  days,
  title = 'สัปดาห์ที่ผ่านมา',
}: {
  days: DayStatus[];
  title?: string;
}) {
  return (
    <div className="bg-panel border border-border rounded-lg p-4">
      <div className="text-sm text-gray-300 mb-3 font-medium">{title}</div>
      <div className="grid grid-cols-7 gap-2">
        {days.map((d) => {
          const color = STATUS_COLOR[d.status];
          const isGrey = d.status === 'no_data' || d.status === 'no_signal' || d.status === 'low_confidence';
          return (
            <div
              key={d.day}
              className="flex flex-col items-center p-2 rounded border border-border"
              style={{
                background: isGrey ? color : `${color}14`,
                borderColor: isGrey ? '#1f242e' : color,
              }}
              title={`${d.day} · ${STATUS_LABEL_TH[d.status]}${
                d.reasons_th[0] ? ' — ' + d.reasons_th[0] : ''
              }`}
            >
              <div className="text-[10px] text-gray-500 uppercase">{d.dow}</div>
              <div className="text-lg font-semibold text-gray-200 mt-1">
                {d.day.slice(8, 10)}
              </div>
              <div
                className="text-[10px] font-medium mt-1"
                style={{ color: isGrey ? '#64748b' : color }}
              >
                {STATUS_LABEL_TH[d.status]}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
