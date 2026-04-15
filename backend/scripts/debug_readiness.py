"""Debug tool: print raw compute_readiness inputs + outputs + penalties.

Usage:
    cd backend
    python -m scripts.debug_readiness <user_id>
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date

if len(sys.argv) < 2:
    print("usage: python -m scripts.debug_readiness <user_id>")
    sys.exit(1)

user_id = sys.argv[1]
parquet_root = Path(__file__).resolve().parent.parent / "data" / "parquet"
user_dir = parquet_root / "users" / user_id
if not user_dir.exists():
    print(f"user dir not found: {user_dir}")
    sys.exit(1)

from app.readiness import (
    _get_today_hrv, _get_today_rhr, _get_prev_steps,
    _get_gym_streak, _get_sleep, _get_today_strain,
    compute_readiness,
)

hrv_val, hrv_base, _hrv_std = _get_today_hrv(user_dir)
rhr_val, rhr_base, _rhr_std = _get_today_rhr(user_dir)
prev_steps = _get_prev_steps(user_dir)
streak = _get_gym_streak(user_dir)
sleep_data = _get_sleep(user_dir)
strain_data = _get_today_strain(user_dir)
dow = date.today().weekday()

print(f"=== user_id: {user_id} ===")
print(f"HRV:           {hrv_val} (base {hrv_base})")
print(f"RHR:           {rhr_val} (base {rhr_base})")
print(f"Prev steps:    {prev_steps}")
print(f"Streak:        {streak}")
print(f"Sleep hrs:     {sleep_data.get('hours')}")
print(f"Bedtime:       {sleep_data.get('bedtime')}")
print(f"Wakeup:        {sleep_data.get('wakeup')}")
print(f"Workouts:      {len(strain_data.get('workouts', []))}")
for w in strain_data.get('workouts', []):
    print(f"  - {w}")
print(f"Active kcal:   {strain_data.get('active_kcal')}")
print(f"Steps today:   {strain_data.get('steps')}")
print(f"DOW:           {dow}")
print()

score, label, color, reason = compute_readiness(
    hrv_val, hrv_base, rhr_val, rhr_base,
    prev_steps, streak, sleep_data.get('hours'), dow,
)
print(f"=== compute_readiness() RAW (before post-compute adjustments) ===")
print(f"Score:  {score}")
print(f"Label:  {label}")
print(f"Color:  {color}")
print(f"Reason: {reason}")
print()

# Apply penalties manually to trace
print(f"=== Post-compute adjustments ===")
adjusted = score
bedtime = sleep_data.get('bedtime')
if bedtime:
    h = int(bedtime.split(':')[0])
    m = int(bedtime.split(':')[1])
    if 1 <= h <= 5:
        adjusted -= 10
        print(f"  -10  late bedtime ({bedtime} → hour 1-5)")
    elif h == 0 and m >= 30:
        adjusted -= 5
        print(f"  -5   bedtime after 00:30 ({bedtime})")

if strain_data.get('workouts'):
    adjusted -= 10
    print(f"  -10  worked out today ({len(strain_data['workouts'])} workouts)")

adjusted = max(0, min(100, adjusted))
print(f"  Final: {adjusted}")
