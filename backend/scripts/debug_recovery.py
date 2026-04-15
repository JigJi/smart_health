"""Recovery score audit — understand WHY today's number landed where it did.

Jig flagged a big gap between our recovery score (e.g. 87%) and Bevel's
(e.g. 40%) on the same physiological state. This script dumps the full
calculation so we can judge whether our model is right, Bevel's is right,
or they're both valid-but-different interpretations.

What it prints:
  1. Today's recovery inputs (raw HRV/RHR/Sleep + baselines)
  2. Each component score (0..1) and its weighted contribution
  3. Final recovery score (should match /today endpoint)
  4. Last 14 days history — is today an anomaly or consistent?
  5. Hypothetical "strain-adjusted" recovery — what would a Bevel-style
     formula give if it penalized recent high strain?
  6. Sleep debt rolling 7-day — are we under-counting chronic deficit?

Usage:
    cd backend
    python -m scripts.debug_recovery <user_id>
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from datetime import date, timedelta
from statistics import mean


def _num(v) -> float:
    """Coerce to float, treating None and NaN as 0 so sum() doesn't poison."""
    if v is None:
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(f) else f


def _to_date(v):
    """Accept datetime/Timestamp/date/str — return date."""
    if hasattr(v, "date"):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])

if len(sys.argv) < 2:
    print("usage: python -m scripts.debug_recovery <user_id>")
    sys.exit(1)

user_id = sys.argv[1]
parquet_root = Path(__file__).resolve().parent.parent / "data" / "parquet"
user_dir = parquet_root / "users" / user_id
if not user_dir.exists():
    print(f"user dir not found: {user_dir}")
    sys.exit(1)

from app.queries import HealthStore
from app.recovery import (
    compute_recovery_series,
    W_HRV, W_RHR, W_SLEEP, SLEEP_TARGET_MIN, BASELINE_DAYS,
)

store = HealthStore(user_dir)
series = compute_recovery_series(store, days=60)
if not series:
    print("No recovery data — need at least 7 days of HRV/RHR history.")
    sys.exit(0)

today = series[-1]
print(f"=== Recovery audit for user_id: {user_id} ===\n")

# ──────────────────────────────────────────────────────────────
# 1. Today's raw inputs + component breakdown
# ──────────────────────────────────────────────────────────────
print(f"📅 Day: {today['day']}")
print()
print("--- Raw signals ---")
print(f"  HRV today:       {today['hrv_today']:.1f} ms" if today['hrv_today'] else "  HRV today:       (no data)")
print(f"  HRV baseline:    {today['hrv_baseline']:.1f} ms" if today['hrv_baseline'] else "  HRV baseline:    (no data)")
if today['hrv_today'] and today['hrv_baseline']:
    delta = today['hrv_today'] - today['hrv_baseline']
    print(f"    → delta:       {delta:+.1f} ms  ({delta / today['hrv_baseline'] * 100:+.1f}%)")

print(f"  RHR today:       {today['rhr_today']:.1f} bpm" if today['rhr_today'] else "  RHR today:       (no data)")
print(f"  RHR baseline:    {today['rhr_baseline']:.1f} bpm" if today['rhr_baseline'] else "  RHR baseline:    (no data)")
if today['rhr_today'] and today['rhr_baseline']:
    delta = today['rhr_today'] - today['rhr_baseline']
    print(f"    → delta:       {delta:+.1f} bpm  (lower is better)")

if today['sleep_today_min']:
    print(f"  Sleep last night: {today['sleep_today_min']:.0f} min ({today['sleep_today_min']/60:.1f} hr)")
    print(f"    → target:      {SLEEP_TARGET_MIN} min ({SLEEP_TARGET_MIN/60:.0f} hr)")

print()
print("--- Component scores (0..1) + weighted contribution ---")
def fmt_score(s, w, label):
    if s is None:
        return f"  {label:<12} (no data)"
    pct = s * 100
    contrib = s * w * 100
    return f"  {label:<12} {pct:>5.1f}%   × weight {w:>4.2f}   → {contrib:>5.1f} pts of final"

print(fmt_score(today['hrv_score'], W_HRV, "HRV"))
print(fmt_score(today['rhr_score'], W_RHR, "RHR"))
print(fmt_score(today['sleep_score'], W_SLEEP, "Sleep"))

# Match what the /today endpoint shows: apply the strain decay overlay so
# this audit number matches what the user actually sees in the dashboard.
# Pre-decay is the "morning signal only" recovery; post-decay adds today's
# completed training load (same calc as readiness.py:836-844).
raw_recovery = today['recovery']
today_kcal = 0.0
workouts_today = store.workouts(days=2)
for w in workouts_today:
    if w.get('start') and _to_date(w['start']) == _to_date(today['day']):
        today_kcal += _num(w.get('active_kcal'))
decay_pct = min(0.30, today_kcal / 1000 * 0.30) if today_kcal else 0
final_recovery = round(raw_recovery * (1 - decay_pct)) if raw_recovery else raw_recovery

print()
print(f"🎯 Recovery (pre-decay, raw morning signal):  {raw_recovery}%")
if today_kcal > 0:
    print(f"   Strain decay overlay: {today_kcal:.0f} kcal → -{decay_pct*100:.0f}%")
    print(f"🎯 Recovery (post-decay, matches /today):    {final_recovery}%")
else:
    print(f"   (no workouts today → no decay, final = raw)")
print()

# ──────────────────────────────────────────────────────────────
# 2. Last 14 days history — is today an anomaly?
# ──────────────────────────────────────────────────────────────
print("--- Last 14 days ---")
print(f"  {'day':<12} {'recov':>6}   {'hrv':>6}   {'rhr':>6}   {'sleep_hr':>8}")
for d in series[-14:]:
    hrv = f"{d['hrv_today']:.1f}" if d['hrv_today'] else "—"
    rhr = f"{d['rhr_today']:.0f}" if d['rhr_today'] else "—"
    sl = f"{d['sleep_today_min']/60:.1f}" if d['sleep_today_min'] else "—"
    recov = f"{d['recovery']:.0f}%" if d['recovery'] else "—"
    print(f"  {d['day']:<12} {recov:>6}   {hrv:>6}   {rhr:>6}   {sl:>8}")

recovs = [d['recovery'] for d in series[-14:] if d['recovery'] is not None]
if recovs:
    print(f"\n  mean 14d:     {mean(recovs):.1f}%")
    print(f"  min 14d:      {min(recovs):.1f}%")
    print(f"  max 14d:      {max(recovs):.1f}%")
    if today['recovery']:
        dev = today['recovery'] - mean(recovs)
        print(f"  today vs avg: {dev:+.1f} pp")

# ──────────────────────────────────────────────────────────────
# 3. Strain-adjusted "what-if" (Bevel-style)
# ──────────────────────────────────────────────────────────────
print()
print("--- What-if: strain-adjusted recovery ---")
print("  (our current formula ignores yesterday's training load)")
print("  (Bevel/Whoop factor acute strain to lower morning recovery)")
print()

# Pull recent workouts to gauge recent strain
workouts = store.workouts(days=7)
if not workouts:
    print("  No workouts in last 7 days → strain adjustment = 0 (no change)")
else:
    today_date = _to_date(today['day'])
    yest = today_date - timedelta(days=1)
    yest_kcal = sum(
        _num(w.get('active_kcal'))
        for w in workouts
        if w.get('start') and _to_date(w['start']) == yest
    )
    last3_kcal = sum(
        _num(w.get('active_kcal'))
        for w in workouts
        if w.get('start') and (today_date - _to_date(w['start'])).days <= 3
    )
    last7_kcal = sum(
        _num(w.get('active_kcal'))
        for w in workouts
        if w.get('start') and (today_date - _to_date(w['start'])).days <= 7
    )
    print(f"  Yesterday workout kcal:   {yest_kcal:.0f}")
    print(f"  Last 3d total kcal:       {last3_kcal:.0f}")
    print(f"  Last 7d total kcal:       {last7_kcal:.0f}")

    # Rough heuristic: if 3-day rolling strain > 1500 kcal, penalize recovery
    # by up to 20 pp (scaled by how much over threshold). This is illustrative —
    # not a claim that Bevel uses this exact formula.
    PENALTY_THRESHOLD = 1500
    PENALTY_MAX = 20
    over = max(0, last3_kcal - PENALTY_THRESHOLD)
    penalty = min(PENALTY_MAX, over / 1000 * PENALTY_MAX)
    if today['recovery'] and penalty > 0:
        adjusted = max(0, today['recovery'] - penalty)
        print(f"\n  Heuristic penalty (rough):  -{penalty:.1f} pp")
        print(f"  Strain-adjusted recovery:   {adjusted:.1f}%")
        print(f"  (vs current {today['recovery']}% — gap of {today['recovery'] - adjusted:.1f} pp)")
    else:
        print(f"\n  No strain penalty applicable (3d strain below threshold)")

# ──────────────────────────────────────────────────────────────
# 4. Sleep debt rolling 7d
# ──────────────────────────────────────────────────────────────
print()
print("--- Sleep debt (rolling 7d) ---")
last7_sleep = [d['sleep_today_min'] for d in series[-7:] if d['sleep_today_min']]
if last7_sleep:
    avg7 = mean(last7_sleep) / 60
    deficit_per_night = (SLEEP_TARGET_MIN / 60) - avg7
    total_deficit = deficit_per_night * 7
    print(f"  Avg sleep 7d:             {avg7:.1f} hr")
    print(f"  Deficit per night:        {deficit_per_night:+.2f} hr (target {SLEEP_TARGET_MIN/60:.0f} hr)")
    print(f"  Cumulative 7d deficit:    {total_deficit:+.1f} hr")
    # Negative deficit_per_night (asleep > target) with a huge 7d total is a
    # sign of DATA corruption, not genuinely sleeping 20 hours a night.
    if avg7 > 11:
        print(f"  🛑 Sleep data looks corrupted (avg {avg7:.1f} hr/night).")
        print(f"     Likely cause: overlapping Asleep-legacy + AsleepCore/Deep/REM stages")
        print(f"     in sleep.parquet being double-summed. Run debug_sleep.py to confirm.")
    elif deficit_per_night > 0.5:
        print("  ⚠️ chronic sleep deficit — our model doesn't currently factor this")
    else:
        print("  ✓ sleep pattern OK over last week")
else:
    print("  Not enough sleep data to compute debt")

# ──────────────────────────────────────────────────────────────
# 5. Diagnosis
# ──────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("DIAGNOSIS:")
print("=" * 60)
print()
print("Our recovery formula:")
print(f"  {W_HRV*100:.0f}% weighted on HRV today vs baseline (z-score)")
print(f"  {W_RHR*100:.0f}% weighted on RHR today vs baseline (z-score, inverted)")
print(f"  {W_SLEEP*100:.0f}% weighted on last night's sleep vs 7hr target")
print()
print("What we DON'T factor (unlike Bevel/Whoop):")
print("  - Yesterday's training strain (acute fatigue)")
print("  - Rolling 7d sleep debt (chronic fatigue)")
print("  - Sleep quality breakdown (deep/REM ratio)")
print("  - Wake-up HR (Whoop uses this)")
print()
print("This means our score reads: 'How recovered are you RIGHT NOW based on")
print("this morning's signals?' — which is defensible but incomplete.")
print()
print("If Bevel shows 40% while we show 87%, likely explanation:")
print("  → Morning signals are good (HRV high, RHR nominal, slept OK)")
print("  → BUT recent training load is high OR sleep debt is real")
print("  → Bevel's more holistic model catches this; ours doesn't")
print()
print("To decide whether to patch:")
print("  1. Is today's strain-adjusted score (above) closer to Bevel's?")
print("  2. Do you FEEL recovered? (subjective truth mirror)")
print("  3. If you feel tired but our score says 87% — our model is wrong.")
print("  4. If you feel great and Bevel says 40% — Bevel is over-penalizing.")
