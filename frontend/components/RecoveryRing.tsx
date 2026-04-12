'use client';

type Props = { value: number | null };

export function RecoveryRing({ value }: Props) {
  const v = value ?? 0;
  const r = 70;
  const c = 2 * Math.PI * r;
  const offset = c - (v / 100) * c;
  const color = v >= 67 ? '#5be49b' : v >= 34 ? '#f7b955' : '#ef5350';

  return (
    <div className="flex flex-col items-center">
      <svg width="180" height="180" viewBox="0 0 180 180">
        <circle cx="90" cy="90" r={r} stroke="#1f242e" strokeWidth="14" fill="none" />
        <circle
          cx="90"
          cy="90"
          r={r}
          stroke={color}
          strokeWidth="14"
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          transform="rotate(-90 90 90)"
          style={{ transition: 'stroke-dashoffset 600ms ease' }}
        />
        <text
          x="90"
          y="95"
          textAnchor="middle"
          fontSize="42"
          fontWeight="600"
          fill="#e6e9ef"
        >
          {value === null ? '—' : Math.round(v)}
        </text>
        <text x="90" y="120" textAnchor="middle" fontSize="12" fill="#8a94a7">
          RECOVERY
        </text>
      </svg>
    </div>
  );
}
