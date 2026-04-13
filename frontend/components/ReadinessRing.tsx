'use client';

const COLORS = {
  green: '#34C759',
  yellow: '#FF9500',
  red: '#FF3B30',
};

export default function ReadinessRing({
  score,
  label,
  color,
}: {
  score: number;
  label: string;
  color: 'green' | 'yellow' | 'red';
}) {
  const size = 180;
  const stroke = 12;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const ringColor = COLORS[color];

  return (
    <div className="flex flex-col items-center py-6">
      <svg width={size} height={size} className="-rotate-90">
        {/* Background track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#F0F0F0"
          strokeWidth={stroke}
        />
        {/* Progress arc */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={ringColor}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 1s ease' }}
        />
      </svg>
      {/* Score text overlay */}
      <div className="flex flex-col items-center -mt-[124px] mb-[44px]">
        <span className="text-5xl font-bold" style={{ color: ringColor }}>
          {score}
        </span>
        <span className="text-base text-secondary mt-1">{label}</span>
      </div>
    </div>
  );
}
