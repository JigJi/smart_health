'use client';

import { ZoneRow } from '@/lib/api';

const ZONE_COLORS: Record<string, string> = {
  Z1: '#64748b',
  Z2: '#22c55e',
  Z3: '#eab308',
  Z4: '#f97316',
  Z5: '#ef4444',
};

export function ZoneBar({
  rows,
  maxHr,
}: {
  rows: ZoneRow[];
  maxHr: number;
}) {
  const bySport = rows.reduce<Record<string, Record<string, number>>>(
    (acc, r) => {
      if (!acc[r.sport]) acc[r.sport] = {};
      acc[r.sport][r.zone] = r.pct;
      return acc;
    },
    {}
  );

  const sports = Object.keys(bySport)
    .filter((s) => {
      const totalSamples = rows
        .filter((r) => r.sport === s)
        .reduce((sum, r) => sum + r.samples, 0);
      return totalSamples >= 500;
    })
    .sort();

  return (
    <div className="bg-panel border border-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-300">
          HR Zone by Sport (max HR {Math.round(maxHr)})
        </h3>
        <div className="flex items-center gap-2 text-xs">
          {['Z1', 'Z2', 'Z3', 'Z4', 'Z5'].map((z) => (
            <span key={z} className="flex items-center gap-1">
              <span
                className="inline-block w-3 h-3 rounded-sm"
                style={{ background: ZONE_COLORS[z] }}
              />
              <span className="text-gray-400">{z}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        {sports.map((sport) => {
          const zones = bySport[sport];
          return (
            <div key={sport} className="flex items-center gap-3">
              <div className="w-40 text-xs text-gray-400 truncate">{sport}</div>
              <div className="flex-1 flex h-6 rounded overflow-hidden border border-border">
                {['Z1', 'Z2', 'Z3', 'Z4', 'Z5'].map((z) => {
                  const pct = zones[z] ?? 0;
                  if (pct === 0) return null;
                  return (
                    <div
                      key={z}
                      style={{
                        width: `${pct}%`,
                        background: ZONE_COLORS[z],
                      }}
                      className="flex items-center justify-center text-[10px] text-black/70 font-medium"
                      title={`${z}: ${pct}%`}
                    >
                      {pct >= 8 ? `${pct.toFixed(0)}%` : ''}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
