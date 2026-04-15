"""Stress metrics — Marco Altini / HRV4Training-style analysis.

Three views, each answering a different question:

  1. ACUTE (today)       — How stressed is the body today? Single-day
                           z-score of morning HRV vs 60-day baseline.
                           Inverted so high value = high stress.

  2. WEEKLY AVG + TREND  — Is stress rising or falling over the week?
                           7-day moving average compared to the prior
                           7-day window. Altini argues trend beats single
                           readings because HRV has high day-to-day noise.

  3. CV (30-day)         — Is the autonomic nervous system stable or
                           erratic? coefficient_of_variation(HRV) over
                           30 days. Low CV = stable. High CV = unstable,
                           a chronic stress / overtraining flag that a
                           single z-score doesn't catch.

All three use morning-only HRV (hour < 10, post-sleep) per Altini's
recommendation to filter daytime noise. Needs ≥7 days of morning
readings for baseline; ≤ that returns partial / None values so the UI
can render "ข้อมูลไม่พอ" rather than show garbage.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import duckdb


def _morning_hrv_by_day(parquet_dir: Path, days: int = 120) -> dict[date, float]:
    """Return {day: avg_hrv_ms} using pre-10am readings only."""
    p = parquet_dir / "hrv_sdnn.parquet"
    if not p.exists():
        return {}
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Bangkok'")
    rows = con.execute(f"""
        SELECT CAST(start AS DATE) AS d, avg(value) AS v
        FROM read_parquet('{p.as_posix()}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL {days} DAY
          AND EXTRACT(hour FROM start) < 10
        GROUP BY 1
    """).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def _stress_from_hrv(hrv_val: float, base_mean: float, base_std: float) -> int:
    """z=0 → 50 (normal), z=-2 → 100 (max stress), z=+2 → 0 (calm).

    Inverted: lower HRV vs baseline = more stress.
    """
    if not base_std:
        return 50
    z = (hrv_val - base_mean) / base_std
    return max(0, min(100, round(50 - z * 25)))


def compute_stress(parquet_dir: Path, target: date | None = None) -> dict[str, Any]:
    """Altini-style stress summary. Returns partial dict when data sparse."""
    d = target or date.today()
    hrv_by_day = _morning_hrv_by_day(parquet_dir, days=120)
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

    # 1. Acute stress today
    today_hrv = hrv_by_day.get(d)
    acute = None
    if today_hrv is not None and base_mean is not None:
        acute = _stress_from_hrv(today_hrv, base_mean, base_std)

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
        "acute": acute,
        "weekly_avg": weekly_avg,
        "weekly_trend": weekly_trend,    # signed pp (+5 = rising, -3 = calming)
        "cv": cv,                        # % — lower is more stable
        "stability": stability,          # stable / variable / unstable / ไม่มีข้อมูล
    }
