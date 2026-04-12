'use client';

import { PersonalNorms } from '@/lib/api';

export function NormsCard({ norms }: { norms: PersonalNorms }) {
  return (
    <div className="bg-panel border border-border rounded-lg p-4">
      <div className="text-sm text-gray-300 font-medium mb-3">
        ค่าปกติของคุณ (จาก {norms.hrv.samples.toLocaleString()} samples · 5 ปี)
      </div>
      <div className="grid grid-cols-2 gap-4">
        <NormBlock
          title="HRV"
          value={`${norms.hrv.median} ms`}
          range={`${norms.hrv.p25} – ${norms.hrv.p75} ms`}
          hint="50% ของวันอยู่ในช่วงนี้ = ปกติ"
          explain="HRV ยิ่งสูง ยิ่งดี · ระบบประสาทพร้อมตอบสนอง"
          color="#8ab4ff"
        />
        <NormBlock
          title="Resting HR"
          value={`${norms.rhr.mean} bpm`}
          range={`${norms.rhr.p25} – ${norms.rhr.p75} bpm`}
          hint="50% ของวันอยู่ในช่วงนี้ = ปกติ"
          explain="RHR ยิ่งต่ำ ยิ่งดี · หัวใจทำงานมีประสิทธิภาพ"
          color="#f7b955"
        />
      </div>
    </div>
  );
}

function NormBlock({
  title,
  value,
  range,
  hint,
  explain,
  color,
}: {
  title: string;
  value: string;
  range: string;
  hint: string;
  explain: string;
  color: string;
}) {
  return (
    <div className="bg-bg/50 border border-border rounded p-3">
      <div className="text-xs uppercase tracking-wider text-gray-500">
        {title} · ของคุณ
      </div>
      <div className="text-2xl font-semibold mt-1" style={{ color }}>
        {value}
      </div>
      <div className="text-xs text-gray-300 mt-2">ช่วงปกติ: {range}</div>
      <div className="text-[10px] text-gray-500 mt-1">{hint}</div>
      <div className="text-[10px] text-gray-500 mt-2 border-t border-border pt-2">
        {explain}
      </div>
    </div>
  );
}
