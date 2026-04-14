"""Personalized tips — learn from user's own workout history.

Core idea: instead of generic "try yoga", we look at what the user
actually did on days with similar state (HRV %, sleep, streak) and
suggest from THEIR vocabulary. If they never yoga, we never yoga.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


# Thai workout names (mirror of narrator_llm.py WK_TH)
WK_TH = {
    "TraditionalStrengthTraining": "เวท",
    "FunctionalStrengthTraining": "Functional Strength",
    "Elliptical": "เครื่องเดิน",
    "Cycling": "ปั่นจักรยาน",
    "Boxing": "มวย",
    "CoreTraining": "Core",
    "HighIntensityIntervalTraining": "HIIT",
    "CardioDance": "เต้น",
    "Walking": "เดิน",
    "Running": "วิ่ง",
    "Yoga": "โยคะ",
    "Swimming": "ว่ายน้ำ",
    "TableTennis": "ปิงปอง",
    "Tennis": "เทนนิส",
    "Other": "อื่นๆ",
}


def _strip_hk_prefix(t: str) -> str:
    return t.replace("HKWorkoutActivityType", "") if t else "Other"


def _th(t: str) -> str:
    return WK_TH.get(_strip_hk_prefix(t), _strip_hk_prefix(t))


def build_activity_profile(parquet_dir: str | Path, days: int = 365) -> dict[str, Any]:
    """Analyze user's workout patterns + state-linked behavior.

    Returns dict with:
      - top_types: [(name_th, count), ...] — user's most-done activities
      - low_hrv_patterns: [(name_th, count), ...] — what they do when HRV low
      - high_hrv_patterns: [(name_th, count), ...] — what they do when HRV high
      - rest_rate_low_hrv: % of low-HRV days user skipped workout
      - preferred_time: 'morning' | 'evening' | 'mixed'
    """
    pq = Path(parquet_dir)
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Bangkok'")

    wk_path = (pq / "workouts.parquet")
    hrv_path = (pq / "hrv_sdnn.parquet")

    profile: dict[str, Any] = {
        "top_types": [],
        "low_hrv_patterns": [],
        "high_hrv_patterns": [],
        "rest_rate_low_hrv": None,
        "preferred_time": None,
    }

    if not wk_path.exists():
        return profile

    # 1. Overall workout preferences (last N days)
    top_rows = con.execute(f"""
        SELECT type, count(*) AS n
        FROM read_parquet('{wk_path.as_posix()}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL {days} DAY
        GROUP BY 1
        ORDER BY n DESC
    """).fetchall()
    profile["top_types"] = [(_th(t[0]), int(t[1])) for t in top_rows if t[1] >= 3]

    # 2. Preferred time of day
    time_rows = con.execute(f"""
        SELECT
          CASE
            WHEN EXTRACT(hour FROM start) < 12 THEN 'morning'
            WHEN EXTRACT(hour FROM start) < 17 THEN 'afternoon'
            WHEN EXTRACT(hour FROM start) < 21 THEN 'evening'
            ELSE 'night'
          END AS period,
          count(*) AS n
        FROM read_parquet('{wk_path.as_posix()}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL {days} DAY
        GROUP BY 1 ORDER BY n DESC
    """).fetchall()
    if time_rows:
        top_period = time_rows[0]
        total = sum(r[1] for r in time_rows)
        if top_period[1] / total > 0.6:
            profile["preferred_time"] = top_period[0]
        else:
            profile["preferred_time"] = "mixed"

    # 3. State-linked patterns — needs HRV data
    if not hrv_path.exists():
        return profile

    # For each day, compute overnight HRV avg and baseline (trailing 60-day median)
    # Then bucket each day into low/normal/high HRV state
    # Then look at what workout (if any) happened that day
    state_rows = con.execute(f"""
        WITH daily_hrv AS (
          SELECT CAST(start AS DATE) AS d, avg(value) AS hrv
          FROM read_parquet('{hrv_path.as_posix()}')
          WHERE CAST(start AS DATE) >= current_date - INTERVAL {days} DAY
            AND EXTRACT(hour FROM start) < 10
          GROUP BY 1
        ),
        with_baseline AS (
          SELECT d, hrv,
                 avg(hrv) OVER (
                   ORDER BY d
                   ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
                 ) AS baseline
          FROM daily_hrv
        ),
        bucketed AS (
          SELECT d, hrv, baseline,
                 CASE
                   WHEN baseline IS NULL THEN 'unknown'
                   WHEN hrv < baseline * 0.85 THEN 'low'
                   WHEN hrv > baseline * 1.10 THEN 'high'
                   ELSE 'normal'
                 END AS state
          FROM with_baseline
        ),
        day_workouts AS (
          SELECT CAST(start AS DATE) AS d,
                 string_agg(type, ',') AS types
          FROM read_parquet('{wk_path.as_posix()}')
          WHERE CAST(start AS DATE) >= current_date - INTERVAL {days} DAY
          GROUP BY 1
        )
        SELECT b.state, b.d, dw.types
        FROM bucketed b
        LEFT JOIN day_workouts dw ON b.d = dw.d
    """).fetchall()

    low_counts: dict[str, int] = {}
    high_counts: dict[str, int] = {}
    low_rest = 0
    low_total = 0
    for state, _d, types in state_rows:
        if state == "low":
            low_total += 1
            if not types:
                low_rest += 1
            else:
                for t in types.split(","):
                    low_counts[_th(t)] = low_counts.get(_th(t), 0) + 1
        elif state == "high":
            if types:
                for t in types.split(","):
                    high_counts[_th(t)] = high_counts.get(_th(t), 0) + 1

    profile["low_hrv_patterns"] = sorted(low_counts.items(), key=lambda x: -x[1])[:5]
    profile["high_hrv_patterns"] = sorted(high_counts.items(), key=lambda x: -x[1])[:5]
    profile["rest_rate_low_hrv"] = (low_rest / low_total) if low_total > 0 else None
    profile["_low_hrv_day_count"] = low_total
    profile["_high_hrv_day_count"] = sum(1 for s, _, _ in state_rows if s == "high")

    return profile


def personalize_recovery_tip(profile: dict[str, Any]) -> dict[str, Any] | None:
    """Given a low-HRV state, build a tip from user's actual past behavior."""
    patterns = profile.get("low_hrv_patterns", [])
    rest_rate = profile.get("rest_rate_low_hrv")

    if not patterns and rest_rate is None:
        return None

    options: list[str] = []
    # Top 2 activities user actually did on low-HRV days
    for name, count in patterns[:2]:
        options.append(f"{name} — คุณเคยทำ {count} ครั้งในวันคล้ายกัน")

    # Rest rate context
    if rest_rate is not None and rest_rate >= 0.2:
        pct = int(rest_rate * 100)
        options.append(f"พักเฉยๆ — คุณเลือกทำ {pct}% ของวันแบบนี้")

    if not options:
        return None

    return {
        "category": "recovery_personal",
        "headline": "วันที่ HRV ต่ำแบบนี้ คุณมักจะ…",
        "options": options[:3],
    }


def personalize_performance_tip(profile: dict[str, Any]) -> dict[str, Any] | None:
    """Given high-HRV state, what does user typically do?"""
    patterns = profile.get("high_hrv_patterns", [])
    if not patterns:
        return None

    options: list[str] = []
    for name, count in patterns[:3]:
        options.append(f"{name} — คุณเคยทำ {count} ครั้งในวันที่พร้อม")

    return {
        "category": "performance_personal",
        "headline": "วันที่ร่างกายพร้อมแบบนี้ คุณมักจะ…",
        "options": options[:3],
    }
