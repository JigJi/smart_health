'use client';

export default function TipCard({ tip }: { tip: string }) {
  return (
    <div className="bg-surface-2 rounded-2xl p-4 flex gap-3 items-start">
      <span className="text-lg mt-0.5">💡</span>
      <p className="text-sm text-secondary leading-relaxed">{tip}</p>
    </div>
  );
}
