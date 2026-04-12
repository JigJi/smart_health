'use client';

import { DayStatus } from '@/lib/api';

const STATUS_TH: Record<string, { label: string; emoji: string; color: string; bg: string }> = {
  normal: {
    label: 'วันนี้ ปกติ',
    emoji: '🟢',
    color: '#5be49b',
    bg: 'rgba(91, 228, 155, 0.08)',
  },
  warning: {
    label: 'วันนี้ ระวัง',
    emoji: '🟡',
    color: '#f7b955',
    bg: 'rgba(247, 185, 85, 0.08)',
  },
  bad: {
    label: 'วันนี้ ไม่ปกติ',
    emoji: '🔴',
    color: '#ef5350',
    bg: 'rgba(239, 83, 80, 0.08)',
  },
  no_data: {
    label: 'ไม่ได้ใส่ Watch',
    emoji: '⚪',
    color: '#64748b',
    bg: 'rgba(100, 116, 139, 0.08)',
  },
  no_signal: {
    label: 'ยังไม่มี reading',
    emoji: '⚪',
    color: '#64748b',
    bg: 'rgba(100, 116, 139, 0.08)',
  },
  low_confidence: {
    label: 'ข้อมูลไม่พอ',
    emoji: '⚪',
    color: '#94a3b8',
    bg: 'rgba(148, 163, 184, 0.06)',
  },
};

export function TodayCard({ day }: { day: DayStatus | null }) {
  if (!day) {
    return (
      <div className="bg-panel border border-border rounded-xl p-6">
        <div className="text-gray-500">ไม่มีข้อมูลวันนี้</div>
      </div>
    );
  }
  const meta = STATUS_TH[day.status] ?? STATUS_TH.no_data;

  return (
    <div
      className="border-2 rounded-xl p-6"
      style={{ borderColor: meta.color, background: meta.bg }}
    >
      <div className="flex items-center justify-between mb-4">
        <div className="text-xs uppercase tracking-wider text-gray-400">
          สถานะวันนี้ · {day.day}
        </div>
        <div className="text-xs text-gray-500">{day.dow}</div>
      </div>

      <div className="flex items-center gap-4 mb-4">
        <div className="text-5xl">{meta.emoji}</div>
        <div>
          <div className="text-3xl font-semibold" style={{ color: meta.color }}>
            {meta.label}
          </div>
          {day.recommendation_th && day.recommendation_th !== '—' && (
            <div className="text-sm text-gray-300 mt-1">
              {day.recommendation_th}
            </div>
          )}
        </div>
      </div>

      {day.reasons_th.length > 0 && (
        <div className="space-y-1 text-sm text-gray-400 border-t border-border pt-3">
          {day.reasons_th.map((r, i) => (
            <div key={i}>• {r}</div>
          ))}
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <StatBox
          label="HRV"
          value={day.hrv_ms != null ? `${day.hrv_ms.toFixed(0)} ms` : '—'}
          baseline={day.hrv_baseline != null ? `ปกติ ~${day.hrv_baseline.toFixed(0)}` : null}
          direction={
            day.hrv_z == null
              ? null
              : day.hrv_z >= 0.3
              ? 'good'
              : day.hrv_z <= -1.0
              ? 'bad'
              : 'neutral'
          }
        />
        <StatBox
          label="RHR"
          value={day.rhr_bpm != null ? `${day.rhr_bpm.toFixed(0)} bpm` : '—'}
          baseline={day.rhr_baseline != null ? `ปกติ ~${day.rhr_baseline.toFixed(0)}` : null}
          direction={
            day.rhr_z == null
              ? null
              : day.rhr_z <= -0.3
              ? 'good'
              : day.rhr_z >= 1.0
              ? 'bad'
              : 'neutral'
          }
        />
      </div>
    </div>
  );
}

function StatBox({
  label,
  value,
  baseline,
  direction,
}: {
  label: string;
  value: string;
  baseline: string | null;
  direction: 'good' | 'bad' | 'neutral' | null;
}) {
  const color =
    direction === 'good'
      ? '#5be49b'
      : direction === 'bad'
      ? '#ef5350'
      : '#e6e9ef';
  return (
    <div className="bg-bg/50 border border-border rounded p-3">
      <div className="text-xs uppercase tracking-wider text-gray-500">{label}</div>
      <div className="text-xl font-semibold mt-1" style={{ color }}>
        {value}
      </div>
      {baseline && <div className="text-xs text-gray-500 mt-1">{baseline}</div>}
    </div>
  );
}
