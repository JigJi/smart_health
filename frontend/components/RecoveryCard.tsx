'use client';

function MiniBar({ label, value }: { label: string; value: number | null }) {
  const v = value ?? 0;
  const color = v >= 67 ? '#34C759' : v >= 34 ? '#FF9500' : '#FF3B30';

  return (
    <div className="flex-1">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-secondary">{label}</span>
        <span className="text-xs font-semibold">{value ?? '—'}%</span>
      </div>
      <div className="w-full h-1.5 bg-border rounded-full">
        <div
          className="h-1.5 rounded-full transition-all duration-700"
          style={{ width: `${v}%`, background: color }}
        />
      </div>
    </div>
  );
}

export default function RecoveryCard({
  score,
  hrvScore,
  rhrScore,
  sleepScore,
}: {
  score: number | null;
  hrvScore: number | null;
  rhrScore: number | null;
  sleepScore: number | null;
}) {
  const v = score ?? 0;
  const color = v >= 67 ? '#34C759' : v >= 34 ? '#FF9500' : '#FF3B30';

  return (
    <div className="bg-surface rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold">ฟื้นตัว</span>
        <span className="text-lg font-bold" style={{ color }}>
          {score ? `${Math.round(score)}%` : '—'}
        </span>
      </div>
      <div className="flex gap-3">
        <MiniBar label="HRV" value={hrvScore} />
        <MiniBar label="RHR" value={rhrScore} />
        <MiniBar label="นอน" value={sleepScore} />
      </div>
    </div>
  );
}
