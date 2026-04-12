'use client';

import { useMemo, useState } from 'react';
import { TimelineEvent } from '@/lib/api';

type Props = {
  events: TimelineEvent[];
  onSelect?: (e: TimelineEvent) => void;
};

const KIND_COLORS: Record<string, string> = {
  anomaly: '#ef5350',
  gap: '#f59e0b',
  drift: '#a78bfa',
  training: '#334155',
  annotation: '#5be49b',
};

const SEVERITY_HEIGHT: Record<string, number> = {
  severe: 12,
  moderate: 9,
  mild: 6,
  info: 4,
};

const ROW_BY_KIND: Record<string, number> = {
  annotation: 0,
  gap: 1,
  anomaly: 2,
  drift: 3,
  training: 4,
};

export function UnifiedTimeline({ events, onSelect }: Props) {
  const [hovered, setHovered] = useState<TimelineEvent | null>(null);

  const { minTime, maxTime, span } = useMemo(() => {
    if (events.length === 0) return { minTime: 0, maxTime: 1, span: 1 };
    const times = events.flatMap((e) => [
      new Date(e.start).getTime(),
      new Date(e.end).getTime(),
    ]);
    const min = Math.min(...times);
    const max = Math.max(...times);
    return { minTime: min, maxTime: max, span: max - min };
  }, [events]);

  const WIDTH = 1100;
  const HEIGHT = 220;
  const PAD = 50;
  const CHART_W = WIDTH - PAD * 2;
  const ROW_GAP = 28;
  const ROW_BASE = 40;

  const xFor = (iso: string) => {
    const t = new Date(iso).getTime();
    return PAD + ((t - minTime) / span) * CHART_W;
  };

  // Year gridlines
  const years = useMemo(() => {
    const out: { year: number; x: number }[] = [];
    const y0 = new Date(minTime).getFullYear();
    const y1 = new Date(maxTime).getFullYear();
    for (let y = y0; y <= y1 + 1; y++) {
      out.push({ year: y, x: xFor(`${y}-01-01`) });
    }
    return out;
  }, [minTime, maxTime]);

  return (
    <div className="bg-panel border border-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-300">
          5-Year Unified Timeline
        </h3>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          {Object.entries(KIND_COLORS).map(([k, c]) => (
            <span key={k} className="flex items-center gap-1">
              <span
                className="inline-block w-3 h-3 rounded-sm"
                style={{ background: c }}
              />
              {k}
            </span>
          ))}
        </div>
      </div>

      <div className="relative overflow-x-auto">
        <svg width={WIDTH} height={HEIGHT}>
          {/* year gridlines */}
          {years.map((y) => (
            <g key={y.year}>
              <line
                x1={y.x}
                x2={y.x}
                y1={20}
                y2={HEIGHT - 20}
                stroke="#1f242e"
                strokeDasharray="2 3"
              />
              <text
                x={y.x}
                y={HEIGHT - 5}
                textAnchor="middle"
                fill="#64748b"
                fontSize={11}
              >
                {y.year}
              </text>
            </g>
          ))}

          {/* row labels */}
          {Object.entries(ROW_BY_KIND).map(([kind, row]) => (
            <text
              key={kind}
              x={PAD - 6}
              y={ROW_BASE + row * ROW_GAP + 4}
              textAnchor="end"
              fontSize={10}
              fill="#8a94a7"
            >
              {kind}
            </text>
          ))}

          {/* events */}
          {events.map((e, i) => {
            const row = ROW_BY_KIND[e.kind] ?? 4;
            const y = ROW_BASE + row * ROW_GAP;
            const x0 = xFor(e.start);
            const x1 = xFor(e.end);
            const w = Math.max(2, x1 - x0);
            const h = SEVERITY_HEIGHT[e.severity] ?? 6;
            const color = KIND_COLORS[e.kind] ?? '#94a3b8';
            const opacity =
              e.severity === 'severe'
                ? 1
                : e.severity === 'moderate'
                ? 0.75
                : e.severity === 'mild'
                ? 0.5
                : 0.4;
            return (
              <rect
                key={i}
                x={x0}
                y={y - h / 2}
                width={w}
                height={h}
                fill={color}
                opacity={opacity}
                rx={2}
                style={{ cursor: 'pointer' }}
                onMouseEnter={() => setHovered(e)}
                onMouseLeave={() => setHovered(null)}
                onClick={() => onSelect?.(e)}
              />
            );
          })}
        </svg>

        {hovered && (
          <div className="absolute top-0 right-0 bg-bg border border-border rounded px-3 py-2 text-xs max-w-xs pointer-events-none">
            <div className="font-medium text-gray-200">{hovered.label}</div>
            <div className="text-gray-500 mt-1">
              {hovered.start} → {hovered.end} · {hovered.days}d · {hovered.severity}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
