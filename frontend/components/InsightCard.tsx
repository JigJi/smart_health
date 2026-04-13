'use client';

export default function InsightCard({
  reason,
  tip,
}: {
  reason: string;
  tip: string;
}) {
  return (
    <div className="bg-surface rounded-2xl p-4">
      <p className="text-sm leading-relaxed text-secondary">{reason}</p>
      <p className="text-sm leading-relaxed text-primary mt-2">{tip}</p>
    </div>
  );
}
