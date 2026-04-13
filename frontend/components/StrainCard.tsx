'use client';

export default function StrainCard({
  activeKcal,
  steps,
  workouts,
}: {
  activeKcal: number;
  steps: number;
  workouts: { type: string; duration_min: number; kcal: number }[];
}) {
  const WORKOUT_NAMES: Record<string, string> = {
    TraditionalStrengthTraining: 'เวท',
    FunctionalStrengthTraining: 'Functional',
    Elliptical: 'เครื่องเดิน',
    Cycling: 'ปั่นจักรยาน',
    Boxing: 'มวย',
    CoreTraining: 'Core',
    HIIT: 'HIIT',
    CardioDance: 'เต้น',
    Walking: 'เดิน',
    Running: 'วิ่ง',
    Yoga: 'โยคะ',
    Swimming: 'ว่ายน้ำ',
    TableTennis: 'ปิงปอง',
  };

  if (workouts.length === 0 && activeKcal === 0) return null;

  return (
    <div className="bg-surface rounded-2xl p-4">
      <h3 className="text-sm font-semibold mb-3">กิจกรรมวันนี้</h3>
      <div className="flex gap-4 text-xs text-secondary mb-3">
        <span>{steps.toLocaleString()} ก้าว</span>
        <span>{activeKcal.toLocaleString()} kcal</span>
      </div>
      {workouts.length > 0 && (
        <div className="space-y-1">
          {workouts.map((w, i) => (
            <div key={i} className="flex justify-between text-xs">
              <span className="text-secondary">
                {WORKOUT_NAMES[w.type] || w.type}
              </span>
              <span className="text-primary font-medium">
                {w.duration_min} นาที · {w.kcal} kcal
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
