"""Debug tool: print raw compute_readiness inputs + outputs.

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
from app.recovery import _zscore_to_unit, W_HRV, W_RHR, W_SLEEP, SLEEP_TARGET_MIN

hrv_val, hrv_base, hrv_std = _get_today_hrv(user_dir)
rhr_val, rhr_base, rhr_std = _get_today_rhr(user_dir)
prev_steps = _get_prev_steps(user_dir)
streak = _get_gym_streak(user_dir)
sleep_data = _get_sleep(user_dir)
strain_data = _get_today_strain(user_dir)
dow = date.today().weekday()
sleep_hours = sleep_data.get("hours")

print(f"=== user_id: {user_id} ===")
print(f"HRV:           {hrv_val} (base {hrv_base}, std {hrv_std})")
print(f"RHR:           {rhr_val} (base {rhr_base}, std {rhr_std})")
print(f"Prev steps:    {prev_steps}")
print(f"Streak:        {streak}")
print(f"Sleep hrs:     {sleep_hours}")
print(f"Bedtime:       {sleep_data.get('bedtime')}")
print(f"Wakeup:        {sleep_data.get('wakeup')}")
print(f"Workouts:      {len(strain_data.get('workouts', []))}")
for w in strain_data.get('workouts', []):
    print(f"  - {w}")
print(f"Active kcal:   {strain_data.get('active_kcal')}")
print(f"Steps today:   {strain_data.get('steps')}")
print(f"Strain score:  {strain_data.get('score')}")
print(f"DOW:           {dow}")
print()

# Compute recovery score (same as get_today)
hrv_score = rhr_score = sleep_score = None
if hrv_val is not None and hrv_base is not None and hrv_std:
    hrv_score = _zscore_to_unit((hrv_val - hrv_base) / hrv_std)
if rhr_val is not None and rhr_base is not None and rhr_std:
    rhr_score = _zscore_to_unit((rhr_base - rhr_val) / rhr_std)
if sleep_hours is not None:
    sq = sleep_data.get("sleep_quality_pct")
    sleep_score = sq / 100.0 if sq is not None else min(1.0, (sleep_hours * 60) / SLEEP_TARGET_MIN)

parts = []
if hrv_score is not None: parts.append((hrv_score, W_HRV))
if rhr_score is not None: parts.append((rhr_score, W_RHR))
if sleep_score is not None: parts.append((sleep_score, W_SLEEP))
recovery_score = None
if parts:
    tw = sum(w for _, w in parts)
    recovery_score = round(100 * sum(s * w for s, w in parts) / tw)

sleep_pct = round(sleep_score * 100) if sleep_score is not None else None

print(f"=== Component scores ===")
print(f"HRV score:     {round(hrv_score*100) if hrv_score else None}")
print(f"RHR score:     {round(rhr_score*100) if rhr_score else None}")
print(f"Sleep score:   {sleep_pct}")
print(f"Recovery:      {recovery_score}")
print(f"Strain:        {strain_data.get('score')}")
print()

score, label, color, reason = compute_readiness(
    recovery_score=recovery_score,
    sleep_score=sleep_pct,
    strain_score=strain_data.get("score", 0),
    bedtime=sleep_data.get("bedtime"),
    today_kcal=strain_data.get("active_kcal", 0) or 0,
    has_workouts=len(strain_data.get("workouts", [])) > 0,
    streak=streak,
    prev_steps=prev_steps,
)
print(f"=== compute_readiness() ===")
print(f"Score:  {score}")
print(f"Label:  {label}")
print(f"Color:  {color}")
print(f"Reason: {reason}")
