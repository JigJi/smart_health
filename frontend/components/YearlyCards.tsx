'use client';

import { YearlySummary } from '@/lib/api';

export function YearlyCards({ years }: { years: YearlySummary[] }) {
  const maxHours = Math.max(...years.map((y) => y.hours || 0), 1);

  return (
    <div className="bg-panel border border-border rounded-lg p-4">
      <h3 className="text-sm font-medium text-gray-300 mb-3">
        Training by Year
      </h3>
      <div className="grid grid-cols-6 gap-3">
        {years.map((y) => {
          const pct = ((y.hours || 0) / maxHours) * 100;
          return (
            <div
              key={y.year}
              className="bg-bg border border-border rounded p-3 relative overflow-hidden"
            >
              <div
                className="absolute bottom-0 left-0 right-0 bg-accent/10"
                style={{ height: `${pct}%` }}
              />
              <div className="relative">
                <div className="text-xs text-gray-500">{y.year}</div>
                <div className="text-lg font-semibold text-gray-100 mt-1">
                  {y.hours?.toFixed(0) ?? '—'}
                  <span className="text-xs text-gray-500 ml-1">h</span>
                </div>
                <div className="text-xs text-gray-400 mt-1">
                  {y.workouts} sessions
                </div>
                {y.avg_hr && (
                  <div className="text-[10px] text-gray-500 mt-1">
                    avg HR {Math.round(y.avg_hr)}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
