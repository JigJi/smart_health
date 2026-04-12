'use client';

type Bucket = { bucket: string; samples: number; pct: number };

export function PolarizationCard({ buckets }: { buckets: Bucket[] }) {
  const byName = Object.fromEntries(buckets.map((b) => [b.bucket, b.pct]));
  const easy = byName.easy ?? 0;
  const moderate = byName.moderate ?? 0;
  const hard = byName.hard ?? 0;

  const idealEasy = 80;
  const idealHard = 20;
  const gapToIdeal = Math.abs(easy - idealEasy) + Math.abs(hard - idealHard);
  const isMtp = moderate > 15; // moderate trap flag

  return (
    <div className="bg-panel border border-border rounded-lg p-4">
      <h3 className="text-sm font-medium text-gray-300 mb-3">
        Training Polarization (365d)
      </h3>
      <div className="flex h-8 rounded overflow-hidden border border-border mb-3">
        <div
          style={{ width: `${easy}%`, background: '#22c55e' }}
          className="flex items-center justify-center text-xs font-medium text-black/70"
        >
          easy {easy}%
        </div>
        <div
          style={{ width: `${moderate}%`, background: '#eab308' }}
          className="flex items-center justify-center text-xs font-medium text-black/70"
        >
          mod {moderate}%
        </div>
        <div
          style={{ width: `${hard}%`, background: '#ef4444' }}
          className="flex items-center justify-center text-xs font-medium text-white/90"
        >
          hard {hard}%
        </div>
      </div>
      <div className="text-xs text-gray-400 grid grid-cols-2 gap-2">
        <div>
          Ideal elite: <span className="text-accent">80% easy</span> ·{' '}
          <span className="text-bad">20% hard</span>
        </div>
        <div className="text-right">
          {isMtp ? (
            <span className="text-warn">⚠ moderate trap</span>
          ) : (
            <span className="text-accent">✓ polarized</span>
          )}
        </div>
      </div>
    </div>
  );
}
