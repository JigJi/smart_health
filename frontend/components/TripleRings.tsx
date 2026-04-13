'use client';

function Ring({
  value,
  label,
  color,
  size = 90,
}: {
  value: number | null;
  label: string;
  color: string;
  size?: number;
}) {
  const stroke = 6;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = value ?? 0;
  const offset = circumference - (pct / 100) * circumference;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative">
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="#2A2A2A"
            strokeWidth={stroke}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            style={{ transition: 'stroke-dashoffset 1s ease' }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg font-bold text-primary">
            {value != null ? `${Math.round(value)}%` : '—'}
          </span>
        </div>
      </div>
      <span className="text-xs text-secondary">{label}</span>
    </div>
  );
}

export default function TripleRings({
  strain,
  recovery,
  sleep,
}: {
  strain: number;
  recovery: number | null;
  sleep: number | null;
}) {
  return (
    <div className="bg-surface rounded-2xl p-5">
      <div className="flex justify-around">
        <Ring value={strain} label="ความหนัก" color="#F5A623" />
        <Ring value={recovery} label="ฟื้นตัว" color="#34C759" />
        <Ring value={sleep} label="การนอน" color="#5E5CE6" />
      </div>
    </div>
  );
}
