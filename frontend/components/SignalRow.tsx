'use client';

const STATUS_ICON: Record<string, { icon: string; color: string }> = {
  good: { icon: '▲', color: '#34C759' },
  normal: { icon: '●', color: '#636366' },
  warning: { icon: '▼', color: '#FF9500' },
  bad: { icon: '▼', color: '#FF3B30' },
  no_data: { icon: '—', color: '#636366' },
};

export default function SignalRow({
  label,
  value,
  unit,
  status,
}: {
  label: string;
  value: string;
  unit?: string;
  status: string;
}) {
  const s = STATUS_ICON[status] || STATUS_ICON.normal;

  return (
    <div className="flex items-center justify-between py-3">
      <span className="text-secondary text-sm">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-primary font-semibold text-sm">
          {value}
          {unit && <span className="text-secondary font-normal ml-0.5">{unit}</span>}
        </span>
        <span style={{ color: s.color }} className="text-xs">
          {s.icon}
        </span>
      </div>
    </div>
  );
}
