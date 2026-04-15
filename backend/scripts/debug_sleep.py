"""Sleep data audit — diagnose the 23.9 hr/night bug flagged on 2026-04-15.

Theory: sleep.parquet contains BOTH the legacy single "Asleep" stage
(pre-iOS 16 API) AND the modern AsleepCore/Deep/REM stages for the same
nights. The query in queries.daily_sleep uses `stage LIKE '%Asleep%'`
which matches both families — so every night gets double- or triple-counted.

This script:
  1. Prints the distinct stages actually present in the parquet
  2. Counts rows per stage
  3. Picks the most recent night and shows every interval Apple recorded
     for it — so we can SEE overlap (start-end ranges per stage)
  4. Re-computes sleep minutes two ways for the last 7 nights:
       (a) current query (LIKE '%Asleep%') — should show inflated numbers
       (b) strict new-stages-only (Core+Deep+REM) — the real sleep duration
  5. Suggests the one-line fix

Usage:
    cd backend
    python -m scripts.debug_sleep <user_id>
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

if len(sys.argv) < 2:
    print("usage: python -m scripts.debug_sleep <user_id>")
    sys.exit(1)

user_id = sys.argv[1]
parquet_root = Path(__file__).resolve().parent.parent / "data" / "parquet"
user_dir = parquet_root / "users" / user_id
sleep_path = user_dir / "sleep.parquet"
if not sleep_path.exists():
    print(f"sleep.parquet not found at {sleep_path}")
    sys.exit(1)

con = duckdb.connect(":memory:")
con.execute("SET TimeZone='Asia/Bangkok'")

print(f"=== Sleep audit for {user_id} ===\n")

# ──────────────────────────────────────────────────────────────
# 1. Distinct stages present
# ──────────────────────────────────────────────────────────────
print("--- Distinct stages in sleep.parquet ---")
rows = con.execute(f"""
    SELECT stage, COUNT(*) AS n,
           MIN(start) AS earliest,
           MAX("end")  AS latest
    FROM read_parquet('{sleep_path.as_posix()}')
    GROUP BY stage
    ORDER BY n DESC
""").fetchall()
for stage, n, earliest, latest in rows:
    print(f"  {stage:<55} {n:>6}   {earliest}  →  {latest}")

# ──────────────────────────────────────────────────────────────
# 2. Does the legacy Asleep stage co-exist with new stages?
# ──────────────────────────────────────────────────────────────
print()
print("--- Legacy-vs-modern coexistence check ---")
row = con.execute(f"""
    WITH by_night AS (
      SELECT CAST("end" AS DATE) AS night,
             SUM(CASE WHEN stage = 'HKCategoryValueSleepAnalysisAsleep'     THEN 1 ELSE 0 END) AS legacy_n,
             SUM(CASE WHEN stage LIKE '%AsleepCore%'                        THEN 1 ELSE 0 END) AS core_n,
             SUM(CASE WHEN stage LIKE '%AsleepDeep%'                        THEN 1 ELSE 0 END) AS deep_n,
             SUM(CASE WHEN stage LIKE '%AsleepREM%'                         THEN 1 ELSE 0 END) AS rem_n
      FROM read_parquet('{sleep_path.as_posix()}')
      GROUP BY 1
    )
    SELECT
      SUM(CASE WHEN legacy_n > 0                         THEN 1 ELSE 0 END) AS nights_with_legacy,
      SUM(CASE WHEN core_n + deep_n + rem_n > 0          THEN 1 ELSE 0 END) AS nights_with_modern,
      SUM(CASE WHEN legacy_n > 0 AND (core_n + deep_n + rem_n) > 0
                                                         THEN 1 ELSE 0 END) AS nights_with_BOTH
    FROM by_night
""").fetchone()
print(f"  Nights with legacy 'Asleep' stage:     {row[0]}")
print(f"  Nights with modern stages:             {row[1]}")
print(f"  🛑 Nights where BOTH coexist:           {row[2]}")
if row[2] and row[2] > 0:
    print()
    print("  → Legacy + modern stages cover the SAME sleep interval")
    print("    and the current query sums both → double-counting.")

# ──────────────────────────────────────────────────────────────
# 3. Show last night's raw intervals — see overlap visually
# ──────────────────────────────────────────────────────────────
print()
print("--- Most recent night's raw intervals ---")
rows = con.execute(f"""
    WITH latest_night AS (
      SELECT MAX(CAST("end" AS DATE)) AS d FROM read_parquet('{sleep_path.as_posix()}')
    )
    SELECT start, "end", stage,
           ROUND(EXTRACT(EPOCH FROM ("end" - start)) / 60.0, 1) AS minutes
    FROM read_parquet('{sleep_path.as_posix()}')
    WHERE CAST("end" AS DATE) = (SELECT d FROM latest_night)
    ORDER BY start
""").fetchall()
total = 0.0
for start, end, stage, minutes in rows:
    stage_short = stage.replace("HKCategoryValueSleepAnalysis", "")
    print(f"  {start.strftime('%H:%M'):<6} → {end.strftime('%H:%M'):<6}  {stage_short:<18} {minutes:>6.1f} min")
    total += float(minutes)
print(f"  {'TOTAL (all rows)':<20}{'':<14}{total:>6.1f} min  ({total/60:.1f} hr)")

# ──────────────────────────────────────────────────────────────
# 4. Current vs strict sum for last 7 nights
# ──────────────────────────────────────────────────────────────
print()
print("--- Last 7 nights: current (LIKE '%Asleep%') vs strict (Core+Deep+REM only) ---")
rows = con.execute(f"""
    SELECT
      CAST("end" AS DATE) AS night,
      ROUND(SUM(CASE WHEN stage LIKE '%Asleep%'
                     THEN EXTRACT(EPOCH FROM ("end" - start))/60 ELSE 0 END), 0) AS current_sum_min,
      ROUND(SUM(CASE WHEN stage LIKE '%AsleepCore%' OR stage LIKE '%AsleepDeep%' OR stage LIKE '%AsleepREM%'
                     THEN EXTRACT(EPOCH FROM ("end" - start))/60 ELSE 0 END), 0) AS strict_sum_min,
      ROUND(SUM(CASE WHEN stage = 'HKCategoryValueSleepAnalysisAsleep'
                     THEN EXTRACT(EPOCH FROM ("end" - start))/60 ELSE 0 END), 0) AS legacy_sum_min
    FROM read_parquet('{sleep_path.as_posix()}')
    WHERE "end" >= current_date - INTERVAL 7 DAY
    GROUP BY 1
    ORDER BY 1
""").fetchall()
print(f"  {'night':<12} {'current':>10} {'strict':>10} {'legacy':>10}")
print(f"  {'':<12} {'min (hr)':>10} {'min (hr)':>10} {'min (hr)':>10}")
for night, cur, strict, legacy in rows:
    cur_f = float(cur or 0)
    st_f = float(strict or 0)
    lg_f = float(legacy or 0)
    print(f"  {str(night):<12} {cur_f:>6.0f}({cur_f/60:.1f}h) {st_f:>6.0f}({st_f/60:.1f}h) {lg_f:>6.0f}({lg_f/60:.1f}h)")

# ──────────────────────────────────────────────────────────────
# 5. Fix suggestion
# ──────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("LIKELY FIX:")
print("=" * 60)
print()
print("In backend/app/queries.py:daily_sleep, replace:")
print()
print("  SUM(CASE WHEN stage LIKE '%Asleep%' THEN minutes ELSE 0 END) AS asleep_min")
print()
print("with:")
print()
print("  SUM(CASE WHEN stage LIKE '%AsleepCore%'")
print("           OR stage LIKE '%AsleepDeep%'")
print("           OR stage LIKE '%AsleepREM%'")
print("      THEN minutes ELSE 0 END) AS asleep_min")
print()
print("Do the same in backend/app/readiness.py:_get_sleep (has identical pattern).")
print()
print("If there are nights with ONLY legacy 'Asleep' (no modern stages), they'd")
print("read 0 after the fix — we'd need to fall back per night. Check the output")
print("above: if 'nights_with_modern' covers every recent night, the simple fix")
print("is safe. Otherwise we need a per-night 'prefer modern, else legacy' CASE.")
