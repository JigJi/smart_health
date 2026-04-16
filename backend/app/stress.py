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

from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import mean, pstdev
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

# Project-wide local timezone — Apple Watch / iOS data is naturally in
# the wearer's local time, and DuckDB queries are set to Asia/Bangkok.
# Stamping this on the cycle_start ISO string lets the JS frontend parse
# unambiguously (without a TZ suffix, browsers fall back to local time
# which can shift the chart x-axis by hours and silently drop points).
_BKK = ZoneInfo("Asia/Bangkok")


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


def _latest_hr_sample_time(parquet_dir: Path, d: date) -> str | None:
    """ISO time of the most recent heart-rate sample on day `d`, or None.

    Why HR (not HRV)? HR samples come every ~6 min when the watch is worn
    (HRV is sparse — ~1 every 1-3 hours). So HR is the dense, reliable
    "watch is currently on the wrist" signal: if the latest HR sample is
    >30 min old, the watch is almost certainly OFF. Used by the UI to
    avoid showing a stale stress reading as "current" — e.g., "stress 68"
    when the user took the watch off at 9 AM and is now opening the app
    at 2 PM. The 68 isn't current; it's the last reading they happened
    to take. The UI uses this signal to say "ไม่ได้สวมนาฬิกา" instead.
    """
    p = parquet_dir / "heart_rate.parquet"
    if not p.exists():
        return None
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Bangkok'")
    row = con.execute(f"""
        SELECT max(start) AS t
        FROM read_parquet('{p.as_posix()}')
        WHERE CAST(start AS DATE) = DATE '{d.isoformat()}'
    """).fetchone()
    if row and row[0]:
        t = row[0]
        return t.isoformat() if hasattr(t, 'isoformat') else str(t)
    return None


def _cycle_start(d: date, bedtime_str: str | None) -> datetime:
    """Start of the 24h "day cycle" anchored on the user's bedtime.

    Per Jig: chart starts when sleep began (when "today" really started
    for the user) and spans 24h ending just before the next bedtime.
    Bedtime hour decides whether the cycle began the previous calendar
    day (evening sleeper, h>=18) or the same calendar day (early-AM
    sleeper, h<12). Defaults to 22:00 if bedtime data missing.
    """
    if bedtime_str:
        try:
            h, m = map(int, bedtime_str.split(":"))
        except (ValueError, AttributeError):
            h, m = 22, 0
    else:
        h, m = 22, 0

    if h < 12:
        # Early-AM bedtime (e.g., 02:30) — cycle starts on day d itself
        return datetime.combine(d, time(h, m))
    # Evening / mid-day bedtime — cycle starts the previous evening
    return datetime.combine(d - timedelta(days=1), time(h, m))


def _hr_samples_for_window(parquet_dir: Path, start_dt: datetime,
                           end_dt: datetime) -> list[tuple[str, float]]:
    """All HR samples in the window [start_dt, end_dt). Dense (~every 6 min
    when watch is worn, more during workouts). Used for the Bevel-style
    stress chart line — HRV alone is too sparse (~5/day) to draw a
    smooth chart, so per-sample stress is computed from HR instead.
    """
    p = parquet_dir / "heart_rate.parquet"
    if not p.exists():
        return []
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Bangkok'")
    rows = con.execute(f"""
        SELECT start, value
        FROM read_parquet('{p.as_posix()}')
        WHERE start >= TIMESTAMP '{start_dt.isoformat()}'
          AND start <  TIMESTAMP '{end_dt.isoformat()}'
        ORDER BY start
    """).fetchall()
    return [(r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0]),
             float(r[1])) for r in rows if r[1] is not None]


def _rhr_baseline(parquet_dir: Path, d: date, days: int = 30) -> float | None:
    """Mean resting heart rate over the last `days` days — personal
    baseline for HR→stress mapping. Returns None if not enough data.
    """
    p = parquet_dir / "resting_heart_rate.parquet"
    if not p.exists():
        return None
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Bangkok'")
    start = (d - timedelta(days=days)).isoformat()
    end = d.isoformat()
    row = con.execute(f"""
        SELECT avg(value), count(*) FROM read_parquet('{p.as_posix()}')
        WHERE CAST(start AS DATE) BETWEEN DATE '{start}' AND DATE '{end}'
    """).fetchone()
    if row and row[0] is not None and row[1] >= 5:
        return float(row[0])
    return None


def _stress_from_hr(hr: float, rhr_baseline: float) -> int:
    """Map heart rate (relative to personal RHR baseline) to 0-100 stress.

    Bevel-style: any HR elevation above resting baseline drives stress
    up. Workouts will spike toward 100 — that's faithful to Bevel and
    physiologically honest (the autonomic nervous system IS firing hard).
    Floor at 5: a living body always has some autonomic activity.

    Mapping (assuming RHR baseline ~60 bpm):
      HR <= RHR        → 5-15  (deeply calm / sleep)
      HR =  RHR + 10   → ~27   (relaxed)
      HR =  RHR + 25   → ~45   (mild activity / mild stress)
      HR =  RHR + 45   → ~69   (moderate activity)
      HR >= RHR + 70   → ~95+  (workout / acute stress)
    """
    delta = hr - rhr_baseline
    if delta <= 0:
        # Below baseline — drop further as HR decreases (sleep / deep rest)
        return max(5, round(15 + delta * 0.5))
    # Above baseline — linear ramp, slope chosen so workouts hit ~95
    return max(5, min(100, round(15 + delta * 1.2)))


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
                   today_kcal: float | None = None,
                   bedtime: str | None = None) -> dict[str, Any]:
    """Stress summary — Bevel-style day-story, not a live gauge.

    Per-sample stress for the chart is now HR-derived (dense ~6 min)
    instead of HRV-derived (sparse ~5/day) so the chart line looks like
    Bevel's — smooth and full. Weekly averages, CV, and stability still
    use HRV (Marco Altini-style autonomic measure across days).

    The 24h "day cycle" is anchored on the user's bedtime — by Jig's
    request, "today" starts when sleep began and ends just before the
    next bedtime. This shifts the chart from a 00:00→00:00 calendar
    cycle to a sleep→sleep biological cycle.

      - current: most recent HR-derived stress sample
      - timeline: HR-derived per-sample stress across the 24h cycle
      - highest / lowest / avg: aggregates across the cycle
      - cycle_start: ISO datetime of the cycle's left edge (frontend uses
        this to anchor the chart x-axis)

    today_kcal param kept for signature stability but unused — physical
    load is already implicit in HR-derived stress (workouts spike HR).
    """
    _ = today_kcal  # intentionally unused; kept for backward-compat
    d = target or date.today()
    hrv_by_day = _all_day_hrv_by_day(parquet_dir, days=120)
    if not hrv_by_day:
        return {"acute": None, "weekly_avg": None, "weekly_trend": None,
                "cv": None, "stability": "ไม่มีข้อมูล"}

    # Baseline for HRV z-score (used by weekly_avg / CV below): 60 days
    # strictly before today
    baseline_pool = [v for dd, v in hrv_by_day.items()
                     if dd < d and (d - dd).days <= 60]
    if len(baseline_pool) >= 7:
        base_mean = mean(baseline_pool)
        base_std = pstdev(baseline_pool) or 1.0
    else:
        base_mean = base_std = None

    # 1. Per-sample stress for the 24h cycle — HR-derived, Bevel-dense.
    #    highest / lowest / average = aggregates over the cycle.
    #    peak_time kept for the "at 10:30" hint on the highest value.
    #    current (= last sample's stress) feeds the prominent value
    #    on the card and the last-point dot on the chart.
    cycle_start_dt = _cycle_start(d, bedtime)
    cycle_end_dt = cycle_start_dt + timedelta(days=1)
    rhr_base = _rhr_baseline(parquet_dir, d)

    current = None
    highest = None
    lowest = None
    peak_time: str | None = None
    avg = None
    timeline: list[dict[str, Any]] = []
    latest_sample_time: str | None = None
    if rhr_base is not None:
        hr_samples = _hr_samples_for_window(parquet_dir, cycle_start_dt, cycle_end_dt)
        if hr_samples:
            per_sample = []
            for t, hr in hr_samples:
                s = _stress_from_hr(hr, rhr_base)
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
        "latest_sample_time": latest_sample_time,  # latest stress sample (= latest HR sample now)
        "latest_hr_sample_time": _latest_hr_sample_time(parquet_dir, d),  # watch-worn signal
        "cycle_start": cycle_start_dt.replace(tzinfo=_BKK).isoformat(),  # left edge of chart x-axis (TZ-stamped)
        "weekly_avg": weekly_avg,
        "weekly_trend": weekly_trend,    # signed pp (+5 = rising, -3 = calming)
        "cv": cv,                        # % — lower is more stable
        "stability": stability,          # stable / variable / unstable / ไม่มีข้อมูล
    }
