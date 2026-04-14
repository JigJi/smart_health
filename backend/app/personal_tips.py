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


# Activity descriptions per state — used to render option text
# without referencing "you did this X times" (that context is in the footer)
DESC_RECOVERY = {
    "เวท": "เวท น้ำหนักเบา–ปานกลาง",
    "เดิน": "เดิน 30–45 นาที (Zone 2 — พูดได้ไม่หอบ)",
    "เครื่องเดิน": "เครื่องเดิน 20–30 นาที (Zone 2)",
    "ปั่นจักรยาน": "ปั่นเบา 30–45 นาที",
    "มวย": "มวย เทคนิค / shadow ไม่เต็ม",
    "Functional Strength": "Functional ระดับเบา",
    "ปิงปอง": "ปิงปอง / Tennis เบาๆ ไม่แข่ง",
    "เทนนิส": "Tennis เบาๆ ไม่แข่ง",
    "ว่ายน้ำ": "ว่ายน้ำ 20–30 นาทีเรื่อยๆ",
    "HIIT": "HIIT เบา — intervals สั้น",
    "วิ่ง": "Jog 20–30 นาที (Zone 2)",
    "โยคะ": "โยคะ / stretching",
    "Core": "Core / mobility",
    "อื่นๆ": "activity เบาๆ",
}

DESC_PERFORMANCE = {
    "เวท": "เวท session หนัก — compound lifts",
    "เดิน": "เดินไกล / long walk",
    "เครื่องเดิน": "เครื่องเดิน intervals",
    "ปั่นจักรยาน": "ปั่นยาว หรือ interval",
    "มวย": "มวย session เต็ม",
    "Functional Strength": "Functional เต็ม session",
    "ปิงปอง": "ปิงปอง / Tennis match",
    "เทนนิส": "Tennis match",
    "ว่ายน้ำ": "ว่ายน้ำ intervals",
    "HIIT": "HIIT / intervals หนัก",
    "วิ่ง": "Run intervals / tempo",
    "โยคะ": "Power yoga / flow",
    "Core": "Core / strength circuit",
    "อื่นๆ": "activity เต็ม capacity",
}


def _describe(name: str, state: str) -> str:
    table = DESC_RECOVERY if state == "recovery" else DESC_PERFORMANCE
    return table.get(name, name)


def build_activity_profile(parquet_dir: str | Path, days: int = 365) -> dict[str, Any]:
    """Analyze user's workout patterns + state-linked behavior.

    Patterns are split by is_weekend because users often behave
    differently on weekday vs weekend (more time, different activities).

    Returns dict with:
      - top_types: [(name_th, count), ...] — user's most-done activities
      - low_hrv_patterns_weekday: what they do on low-HRV weekdays
      - low_hrv_patterns_weekend: what they do on low-HRV weekends
      - high_hrv_patterns_weekday / weekend: same split for high-HRV
      - rest_rate_low_hrv_weekday / weekend
      - preferred_time: 'morning' | 'evening' | 'mixed'
    """
    pq = Path(parquet_dir)
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Bangkok'")

    wk_path = (pq / "workouts.parquet")
    hrv_path = (pq / "hrv_sdnn.parquet")

    profile: dict[str, Any] = {
        "top_types": [],
        "low_hrv_patterns_weekday": [],
        "low_hrv_patterns_weekend": [],
        "high_hrv_patterns_weekday": [],
        "high_hrv_patterns_weekend": [],
        "rest_rate_low_hrv_weekday": None,
        "rest_rate_low_hrv_weekend": None,
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
        SELECT b.state, b.d, EXTRACT(DOW FROM b.d) AS dow, dw.types
        FROM bucketed b
        LEFT JOIN day_workouts dw ON b.d = dw.d
    """).fetchall()

    # Split counters by is_weekend (DOW: 0=Sun, 6=Sat in DuckDB; weekend = 0 or 6)
    buckets = {
        "low_weekday": {"counts": {}, "rest": 0, "total": 0},
        "low_weekend": {"counts": {}, "rest": 0, "total": 0},
        "high_weekday": {"counts": {}, "rest": 0, "total": 0},
        "high_weekend": {"counts": {}, "rest": 0, "total": 0},
    }

    for state, _d, dow, types in state_rows:
        if state not in ("low", "high"):
            continue
        is_weekend = int(dow) in (0, 6)
        key = f"{state}_{'weekend' if is_weekend else 'weekday'}"
        buckets[key]["total"] += 1
        if not types:
            buckets[key]["rest"] += 1
        else:
            for t in types.split(","):
                name = _th(t)
                buckets[key]["counts"][name] = buckets[key]["counts"].get(name, 0) + 1

    def _top(bucket):
        return sorted(bucket["counts"].items(), key=lambda x: -x[1])[:5]

    def _rest_rate(bucket):
        return (bucket["rest"] / bucket["total"]) if bucket["total"] > 0 else None

    profile["low_hrv_patterns_weekday"] = _top(buckets["low_weekday"])
    profile["low_hrv_patterns_weekend"] = _top(buckets["low_weekend"])
    profile["high_hrv_patterns_weekday"] = _top(buckets["high_weekday"])
    profile["high_hrv_patterns_weekend"] = _top(buckets["high_weekend"])
    profile["rest_rate_low_hrv_weekday"] = _rest_rate(buckets["low_weekday"])
    profile["rest_rate_low_hrv_weekend"] = _rest_rate(buckets["low_weekend"])
    profile["_low_weekday_n"] = buckets["low_weekday"]["total"]
    profile["_low_weekend_n"] = buckets["low_weekend"]["total"]

    return profile


def personalize_recovery_tip(profile: dict[str, Any], is_weekend: bool) -> dict[str, Any] | None:
    """Low-HRV state: suggest activities from user's top list, described generically.
    Uses weekday or weekend bucket to pick relevant types."""
    key = "weekend" if is_weekend else "weekday"
    patterns = profile.get(f"low_hrv_patterns_{key}", [])
    rest_rate = profile.get(f"rest_rate_low_hrv_{key}")

    if not patterns and rest_rate is None:
        return None

    options: list[str] = []
    seen: set[str] = set()
    for name, _count in patterns[:2]:
        desc = _describe(name, "recovery")
        if desc not in seen:
            options.append(desc)
            seen.add(desc)

    # Include rest option if user historically rests often in this state
    if rest_rate is not None and rest_rate >= 0.2:
        options.append("พัก (ไม่ออกกำลัง)")

    if not options:
        return None

    return {
        "category": "recovery_personal",
        "headline": None,  # set by caller — includes HRV %
        "options": options[:3],
    }


def personalize_performance_tip(profile: dict[str, Any], is_weekend: bool) -> dict[str, Any] | None:
    """High-HRV state: pick from user's top types (weekday/weekend split)."""
    key = "weekend" if is_weekend else "weekday"
    patterns = profile.get(f"high_hrv_patterns_{key}", [])
    if not patterns:
        return None

    options: list[str] = []
    seen: set[str] = set()
    for name, _count in patterns[:3]:
        desc = _describe(name, "performance")
        if desc not in seen:
            options.append(desc)
            seen.add(desc)

    if not options:
        return None

    return {
        "category": "performance_personal",
        "headline": None,
        "options": options[:3],
    }
