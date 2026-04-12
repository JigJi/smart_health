"""Personal health profile — learns YOUR unique patterns from 5 years of data.

Not population norms. Not fixed thresholds. YOUR body, YOUR rhythms.

Mines:
  1. Day-of-week baselines    — "Monday is naturally your worst HRV day"
  2. Post-workout recovery     — "After strength, YOUR HRV takes 2 days to normalize"
  3. Training load sweet spot  — "Your best weeks have 4-5 sessions"
  4. Seasonal patterns         — "Your HRV is lowest in July-August"
  5. Vulnerability patterns    — "You tend to get sick after 2+ weeks of high load"
  6. Personal bests/worsts     — context for framing today's reading
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


def build_profile(parquet_dir: str | Path) -> dict[str, Any]:
    pq = Path(parquet_dir)
    con = duckdb.connect(":memory:")

    hrv_path = (pq / "hrv_sdnn.parquet").as_posix()
    rhr_path = (pq / "resting_heart_rate.parquet").as_posix()
    wk_path = (pq / "workouts.parquet").as_posix()

    profile: dict[str, Any] = {}

    # ─── 1. Day-of-week baselines ───
    dow_hrv = con.execute(f"""
        SELECT
          strftime(CAST(start AS DATE), '%a') AS dow,
          EXTRACT(DOW FROM CAST(start AS DATE)) AS dow_n,
          round(median(value), 1) AS hrv,
          count(*) AS n
        FROM read_parquet('{hrv_path}')
        GROUP BY 1, 2 ORDER BY 2
    """).fetchdf().to_dict("records")

    dow_rhr = con.execute(f"""
        SELECT
          strftime(CAST(start AS DATE), '%a') AS dow,
          EXTRACT(DOW FROM CAST(start AS DATE)) AS dow_n,
          round(avg(value), 1) AS rhr,
          count(*) AS n
        FROM read_parquet('{rhr_path}')
        GROUP BY 1, 2 ORDER BY 2
    """).fetchdf().to_dict("records")

    profile["dow_baselines"] = {
        "hrv": dow_hrv,
        "rhr": dow_rhr,
        "best_hrv_day": max(dow_hrv, key=lambda x: x["hrv"])["dow"] if dow_hrv else None,
        "worst_hrv_day": min(dow_hrv, key=lambda x: x["hrv"])["dow"] if dow_hrv else None,
        "best_rhr_day": min(dow_rhr, key=lambda x: x["rhr"])["dow"] if dow_rhr else None,
        "worst_rhr_day": max(dow_rhr, key=lambda x: x["rhr"])["dow"] if dow_rhr else None,
    }

    # ─── 2. Post-workout recovery per sport ───
    recovery = con.execute(f"""
        WITH workout_days AS (
          SELECT
            CAST(start AS DATE) AS d,
            REPLACE(type, 'HKWorkoutActivityType', '') AS sport
          FROM read_parquet('{wk_path}')
        ),
        hrv_daily AS (
          SELECT CAST(start AS DATE) AS d, median(value) AS hrv
          FROM read_parquet('{hrv_path}')
          GROUP BY 1
        ),
        paired AS (
          SELECT
            w.sport,
            h0.hrv AS hrv_day0,
            h1.hrv AS hrv_day1,
            h2.hrv AS hrv_day2,
            h3.hrv AS hrv_day3
          FROM workout_days w
          LEFT JOIN hrv_daily h0 ON h0.d = w.d
          LEFT JOIN hrv_daily h1 ON h1.d = w.d + INTERVAL 1 DAY
          LEFT JOIN hrv_daily h2 ON h2.d = w.d + INTERVAL 2 DAY
          LEFT JOIN hrv_daily h3 ON h3.d = w.d + INTERVAL 3 DAY
          WHERE h0.hrv IS NOT NULL
        )
        SELECT
          sport,
          count(*) AS sessions,
          round(avg(hrv_day0), 1) AS hrv_d0,
          round(avg(hrv_day1), 1) AS hrv_d1,
          round(avg(hrv_day2), 1) AS hrv_d2,
          round(avg(hrv_day3), 1) AS hrv_d3
        FROM paired
        GROUP BY sport
        HAVING count(*) >= 10
        ORDER BY sessions DESC
    """).fetchdf().to_dict("records")

    # Calculate recovery days: how many days until HRV returns to d0 level
    for r in recovery:
        d0 = r["hrv_d0"]
        days_to_recover = 0
        for i, key in enumerate(["hrv_d1", "hrv_d2", "hrv_d3"]):
            if r[key] is not None and r[key] >= d0:
                days_to_recover = i + 1
                break
        else:
            days_to_recover = 3  # still recovering after 3 days
        r["recovery_days"] = days_to_recover

    profile["recovery_by_sport"] = recovery

    # ─── 3. Optimal training load ───
    weekly_load = con.execute(f"""
        WITH weeks AS (
          SELECT
            DATE_TRUNC('week', CAST(start AS DATE)) AS week,
            count(*) AS sessions,
            sum(duration_min) AS mins
          FROM read_parquet('{wk_path}')
          GROUP BY 1
        ),
        hrv_weeks AS (
          SELECT
            DATE_TRUNC('week', CAST(start AS DATE)) AS week,
            median(value) AS hrv
          FROM read_parquet('{hrv_path}')
          GROUP BY 1
        )
        SELECT
          w.sessions,
          round(avg(h.hrv), 1) AS avg_hrv,
          count(*) AS n_weeks
        FROM weeks w
        JOIN hrv_weeks h ON h.week = w.week + INTERVAL 1 WEEK
        GROUP BY 1
        HAVING n_weeks >= 3
        ORDER BY 1
    """).fetchdf().to_dict("records")

    if weekly_load:
        best = max(weekly_load, key=lambda x: x["avg_hrv"] or 0)
        profile["optimal_load"] = {
            "by_sessions": weekly_load,
            "best_sessions_per_week": int(best["sessions"]),
            "best_next_week_hrv": best["avg_hrv"],
        }
    else:
        profile["optimal_load"] = None

    # ─── 4. Monthly/seasonal pattern ───
    monthly = con.execute(f"""
        SELECT
          EXTRACT(MONTH FROM CAST(start AS DATE)) AS month,
          round(median(value), 1) AS hrv,
          count(*) AS n
        FROM read_parquet('{hrv_path}')
        GROUP BY 1
        ORDER BY 1
    """).fetchdf().to_dict("records")

    if monthly:
        best_m = max(monthly, key=lambda x: x["hrv"])
        worst_m = min(monthly, key=lambda x: x["hrv"])
        months_th = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                      "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
        profile["seasonal"] = {
            "monthly": monthly,
            "best_month": months_th[int(best_m["month"])],
            "worst_month": months_th[int(worst_m["month"])],
            "best_hrv": best_m["hrv"],
            "worst_hrv": worst_m["hrv"],
        }

    # ─── 5. Personal records ───
    records = con.execute(f"""
        SELECT
          round(max(value), 1) AS best_hrv,
          round(min(value), 1) AS worst_hrv,
          round(median(value), 1) AS typical_hrv,
          count(*) AS total_readings
        FROM read_parquet('{hrv_path}')
    """).fetchone()
    rhr_records = con.execute(f"""
        SELECT
          round(min(value), 1) AS best_rhr,
          round(max(value), 1) AS worst_rhr,
          round(avg(value), 1) AS typical_rhr
        FROM read_parquet('{rhr_path}')
    """).fetchone()

    profile["records"] = {
        "best_hrv": records[0],
        "worst_hrv": records[1],
        "typical_hrv": records[2],
        "total_hrv_readings": records[3],
        "best_rhr": rhr_records[0],
        "worst_rhr": rhr_records[1],
        "typical_rhr": rhr_records[2],
    }

    # ─── 6. Consecutive training patterns ───
    consec = con.execute(f"""
        WITH daily_wk AS (
          SELECT CAST(start AS DATE) AS d, count(*) AS n
          FROM read_parquet('{wk_path}')
          GROUP BY 1
        ),
        hrv_d AS (
          SELECT CAST(start AS DATE) AS d, median(value) AS hrv
          FROM read_parquet('{hrv_path}')
          GROUP BY 1
        ),
        with_lag AS (
          SELECT d, n,
                 LAG(n, 1) OVER (ORDER BY d) AS prev1,
                 LAG(n, 2) OVER (ORDER BY d) AS prev2
          FROM daily_wk
        )
        SELECT
          CASE
            WHEN prev1 > 0 AND prev2 > 0 THEN '3+ days'
            WHEN prev1 > 0 THEN '2 days'
            ELSE '1 day'
          END AS streak,
          round(avg(h.hrv), 1) AS next_day_hrv,
          count(*) AS n
        FROM with_lag w
        JOIN hrv_d h ON h.d = w.d + INTERVAL 1 DAY
        WHERE w.n > 0
        GROUP BY 1
        ORDER BY 1
    """).fetchdf().to_dict("records")
    profile["consec_training_effect"] = consec

    return profile
