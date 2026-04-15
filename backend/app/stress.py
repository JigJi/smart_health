"""Stress metrics — Marco Altini / HRV4Training-style analysis.

Three views, each answering a different question:

  1. ACUTE (today)       — How stressed is the body RIGHT NOW?
                           z-score of today's all-day HRV average vs
                           personal 60-day all-day baseline. Inverted so
                           high value = high stress. Uses all-day (not
                           morning-only) because stress reflects current
                           physiological state — post-workout HRV drops
                           should show up, which morning-only would miss.

  2. WEEKLY AVG + TREND  — Is stress rising or falling over the week?
                           7-day moving average compared to the prior
                           7-day window. Altini argues trend beats single
                           readings because HRV has high day-to-day noise.

  3. CV (30-day)         — Is the autonomic nervous system stable or
                           erratic? coefficient_of_variation(HRV) over
                           30 days. Low CV = stable. High CV = unstable,
                           a chronic stress / overtraining flag that a
                           single z-score doesn't catch.

Split from Recovery on purpose:
  Recovery uses MORNING HRV (Altini gold — post-sleep readiness signal,
  doesn't change through the day; afternoon decay comes from strain).
  Stress uses ALL-DAY HRV (includes post-meal / post-workout drops —
  reflects current autonomic state, which is what "stress" means to users).

Needs ≥7 days of baseline; less than that returns partial / None values
so the UI can render "ข้อมูลไม่พอ" rather than show garbage.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import duckdb


def _all_day_hrv_by_day(parquet_dir: Path, days: int = 120) -> dict[date, float]:
    """Return {day: avg_hrv_ms} using ALL readings across the day.

    Stress wants current-state signal — post-workout / post-coffee HRV
    drops must land in the number. Morning-only filter would mask those.
    """
    p = parquet_dir / "hrv_sdnn.parquet"
    if not p.exists():
        return {}
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Bangkok'")
    rows = con.execute(f"""
        SELECT CAST(start AS DATE) AS d, avg(value) AS v
        FROM read_parquet('{p.as_posix()}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL {days} DAY
        GROUP BY 1
    """).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def _hrv_samples_for_day(parquet_dir: Path, d: date) -> list[tuple[str, float]]:
    """Return list of (iso_time, hrv_ms) for all HRV samples on day `d`.

    Used to compute per-moment stress throughout the day so the UI can
    show a timeline instead of a single number. Apple Watch logs HRV
    sporadically (5-10 per day typically), so the timeline is sparse —
    callers should handle low-sample cases gracefully.
    """
    p = parquet_dir / "hrv_sdnn.parquet"
    if not p.exists():
        return []
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Bangkok'")
    rows = con.execute(f"""
        SELECT start, value
        FROM read_parquet('{p.as_posix()}')
        WHERE CAST(start AS DATE) = DATE '{d.isoformat()}'
        ORDER BY start
    """).fetchall()
    return [(r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0]),
             float(r[1])) for r in rows if r[1] is not None]


def _stress_from_hrv(hrv_val: float, base_mean: float, base_std: float) -> int:
    """z=0 → 50 (normal), z=-2 → 100 (max stress), z=+2 → ~5 (calm floor).

    Inverted: lower HRV vs baseline = more stress. Clamped to [5, 100]
    because physiologically a living body always has some autonomic
    activity — 0 looks like a bug, not "perfectly relaxed." Bevel
    also floors around 5-6 in practice.
    """
    if not base_std:
        return 50
    z = (hrv_val - base_mean) / base_std
    return max(5, min(100, round(50 - z * 25)))


def compute_stress(parquet_dir: Path, target: date | None = None,
                   today_kcal: float | None = None) -> dict[str, Any]:
    """Stress summary — Bevel-style day-story, not a live gauge.

    Computes per-sample stress from HRV readings today, then summarizes:
      - current: most recent sample (fresh when app syncs)
      - peak:    highest stress moment today (usually during workout)
      - avg:     mean across today
      - timeline: list of {time, stress} for UI chart

    No physical-load boost here (that's a separate axis already shown as
    "ความเหนื่อยล้า"). Stress is pure autonomic / HRV-derived.

    today_kcal param kept for signature stability but unused — remove
    on next pass if no caller needs it. (Strain-boost approach double-
    counted with the strain metric and was explicitly rejected by Jig
    after seeing the scary 78% number it produced on a restful evening.)

    Returns partial dict when data sparse.
    """
    _ = today_kcal  # intentionally unused; kept for backward-compat
    d = target or date.today()
    hrv_by_day = _all_day_hrv_by_day(parquet_dir, days=120)
    if not hrv_by_day:
        return {"acute": None, "weekly_avg": None, "weekly_trend": None,
                "cv": None, "stability": "ไม่มีข้อมูล"}

    # Baseline for z-score: 60 days strictly before today
    baseline_pool = [v for dd, v in hrv_by_day.items()
                     if dd < d and (d - dd).days <= 60]
    if len(baseline_pool) >= 7:
        base_mean = mean(baseline_pool)
        base_std = pstdev(baseline_pool) or 1.0
    else:
        base_mean = base_std = None

    # 1. Per-sample stress today — Bevel-style summary.
    #    highest / lowest / average = what the UI shows as 3 numbers.
    #    peak_time kept for the "at 10:30" hint on the highest value.
    #    current (= latest sample) drives the gauge position.
    current = None
    highest = None
    lowest = None
    peak_time: str | None = None
    avg = None
    timeline: list[dict[str, Any]] = []
    latest_sample_time: str | None = None
    if base_mean is not None:
        samples = _hrv_samples_for_day(parquet_dir, d)
        if samples:
            per_sample = []
            for t, v in samples:
                s = _stress_from_hrv(v, base_mean, base_std)
                per_sample.append((t, s))
                timeline.append({"time": t, "stress": s})
            stresses = [s for _, s in per_sample]
            current = per_sample[-1][1]
            highest = max(stresses)
            lowest = min(stresses)
            peak_time = next(t for t, s in per_sample if s == highest)
            avg = round(mean(stresses))
            latest_sample_time = per_sample[-1][0]

    # Acute / peak = backward-compat aliases for highest
    acute = current
    peak = highest

    # 2. Weekly avg + trend (this 7d vs prior 7d)
    def _window_stress(start_offset: int, size: int = 7) -> float | None:
        vals = []
        for i in range(start_offset, start_offset + size):
            day = d - timedelta(days=i)
            hv = hrv_by_day.get(day)
            if hv is not None and base_mean is not None:
                vals.append(_stress_from_hrv(hv, base_mean, base_std))
        return round(mean(vals)) if len(vals) >= 3 else None

    weekly_avg = _window_stress(0, 7)    # last 7 days incl today
    prev_week  = _window_stress(7, 7)    # 8-14 days ago
    weekly_trend = None
    if weekly_avg is not None and prev_week is not None:
        weekly_trend = weekly_avg - prev_week  # positive = stress rising

    # 3. CV over last 30 days — autonomic stability indicator
    last_30 = [v for dd, v in hrv_by_day.items()
               if (d - dd).days <= 30 and dd <= d]
    cv = None
    stability = "ไม่มีข้อมูล"
    if len(last_30) >= 14:
        m = mean(last_30)
        s = pstdev(last_30)
        if m > 0:
            cv = round(s / m * 100, 1)
            if cv < 15:
                stability = "stable"
            elif cv < 25:
                stability = "variable"
            else:
                stability = "unstable"

    return {
        "acute": acute,                  # backward-compat alias for current
        "current": current,               # latest sample (drives gauge position)
        "highest": highest,               # max stress today
        "lowest": lowest,                 # min stress today
        "peak": peak,                     # backward-compat alias for highest
        "peak_time": peak_time,           # ISO time of highest moment
        "avg": avg,                       # mean stress today
        "timeline": timeline,             # [{time, stress}] — kept for any future chart need
        "latest_sample_time": latest_sample_time,  # freshness indicator
        "weekly_avg": weekly_avg,
        "weekly_trend": weekly_trend,    # signed pp (+5 = rising, -3 = calming)
        "cv": cv,                        # % — lower is more stable
        "stability": stability,          # stable / variable / unstable / ไม่มีข้อมูล
    }
