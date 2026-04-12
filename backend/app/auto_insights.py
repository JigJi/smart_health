"""Auto-generated insights — zero manual input required.

Instead of asking the user to log behaviors, we infer them from
existing data and correlate with next-day biometrics. This answers
questions like:
  - "After a hard workout, how does your body respond?"
  - "After 3+ rest days, what happens to your HRV?"
  - "Weekdays vs weekends — which is better for your body?"
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb


def auto_insights(parquet_dir: str | Path) -> list[dict[str, Any]]:
    pq = Path(parquet_dir)
    con = duckdb.connect(":memory:")

    hrv_path = (pq / "hrv_sdnn.parquet").as_posix()
    rhr_path = (pq / "resting_heart_rate.parquet").as_posix()
    wk_path = (pq / "workouts.parquet").as_posix()
    hr_path = (pq / "heart_rate.parquet").as_posix()

    # Build daily context table
    con.execute(f"""
        CREATE TEMP TABLE daily AS
        WITH hrv AS (
          SELECT CAST(start AS DATE) AS d, median(value) AS hrv
          FROM read_parquet('{hrv_path}') GROUP BY 1
        ),
        rhr AS (
          SELECT CAST(start AS DATE) AS d, avg(value) AS rhr
          FROM read_parquet('{rhr_path}') GROUP BY 1
        ),
        wk AS (
          SELECT CAST(start AS DATE) AS d,
                 count(*) AS n_workouts,
                 sum(duration_min) AS workout_min,
                 max(hr_avg) AS max_workout_hr
          FROM read_parquet('{wk_path}') GROUP BY 1
        ),
        hr AS (
          SELECT CAST(start AS DATE) AS d, count(*) AS hr_samples
          FROM read_parquet('{hr_path}') GROUP BY 1
        )
        SELECT
          COALESCE(hrv.d, rhr.d) AS d,
          hrv.hrv,
          rhr.rhr,
          COALESCE(wk.n_workouts, 0) AS n_workouts,
          COALESCE(wk.workout_min, 0) AS workout_min,
          wk.max_workout_hr,
          COALESCE(hr.hr_samples, 0) AS hr_samples
        FROM hrv
        FULL OUTER JOIN rhr USING (d)
        LEFT JOIN wk USING (d)
        LEFT JOIN hr USING (d)
        WHERE COALESCE(hrv.d, rhr.d) IS NOT NULL
    """)

    insights: list[dict[str, Any]] = []

    # ─── 1. Hard workout effect ───
    _compare(
        con, insights,
        tag_name="hard_workout",
        icon="💪",
        label_th="ออกกำลังกายหนัก",
        condition="n_workouts > 0 AND max_workout_hr > (SELECT quantile(max_workout_hr, 0.75) FROM daily WHERE max_workout_hr IS NOT NULL)",
        neg_condition="n_workouts = 0 OR max_workout_hr <= (SELECT quantile(max_workout_hr, 0.75) FROM daily WHERE max_workout_hr IS NOT NULL)",
    )

    # ─── 2. Rest day effect ───
    _compare(
        con, insights,
        tag_name="rest_day",
        icon="🛋️",
        label_th="วันพัก (ไม่ออกกำลัง)",
        condition="n_workouts = 0",
        neg_condition="n_workouts > 0",
    )

    # ─── 3. Double workout day ───
    _compare(
        con, insights,
        tag_name="double_workout",
        icon="🔥",
        label_th="ออกกำลัง 2+ ครั้ง/วัน",
        condition="n_workouts >= 2",
        neg_condition="n_workouts = 1",
    )

    # ─── 4. Weekday vs Weekend ───
    _compare(
        con, insights,
        tag_name="weekday",
        icon="🏢",
        label_th="วันทำงาน (จ-ศ)",
        condition="EXTRACT(DOW FROM d) BETWEEN 1 AND 5",
        neg_condition="EXTRACT(DOW FROM d) IN (0, 6)",
        neg_label="weekend",
    )

    # ─── 5. Long rest streak (3+ days no workout) ───
    con.execute("""
        CREATE TEMP TABLE streaks AS
        WITH lagged AS (
          SELECT d, n_workouts,
                 LAG(n_workouts, 1) OVER (ORDER BY d) AS prev1,
                 LAG(n_workouts, 2) OVER (ORDER BY d) AS prev2
          FROM daily
        )
        SELECT d, 1 AS after_long_rest
        FROM lagged
        WHERE prev1 = 0 AND prev2 = 0 AND n_workouts = 0
    """)
    _compare(
        con, insights,
        tag_name="long_rest",
        icon="😴",
        label_th="หลังพัก 3+ วันติด",
        condition="d IN (SELECT d FROM streaks)",
        neg_condition="d NOT IN (SELECT d FROM streaks)",
    )

    # ─── 6. Consecutive training days (2+ days with workout) ───
    con.execute("""
        CREATE TEMP TABLE consec AS
        WITH lagged AS (
          SELECT d, n_workouts,
                 LAG(n_workouts, 1) OVER (ORDER BY d) AS prev1
          FROM daily
        )
        SELECT d, 1 AS consec_train
        FROM lagged
        WHERE n_workouts > 0 AND prev1 > 0
    """)
    _compare(
        con, insights,
        tag_name="consec_training",
        icon="📈",
        label_th="ออกกำลัง 2 วันติด",
        condition="d IN (SELECT d FROM consec)",
        neg_condition="d NOT IN (SELECT d FROM consec) AND n_workouts > 0",
    )

    insights.sort(key=lambda x: abs(x.get("hrv_diff_pct", 0)), reverse=True)
    return insights


def _compare(
    con: duckdb.DuckDBPyConnection,
    results: list[dict],
    *,
    tag_name: str,
    icon: str,
    label_th: str,
    condition: str,
    neg_condition: str,
    neg_label: str = "",
) -> None:
    """Compare next-day HRV/RHR for rows matching condition vs not."""
    sql = f"""
        WITH tagged AS (
          SELECT d FROM daily WHERE {condition}
        ),
        untagged AS (
          SELECT d FROM daily WHERE {neg_condition}
        )
        SELECT
          (SELECT avg(b.hrv) FROM daily b WHERE b.d IN (SELECT d + INTERVAL 1 DAY FROM tagged) AND b.hrv IS NOT NULL) AS hrv_with,
          (SELECT avg(b.hrv) FROM daily b WHERE b.d IN (SELECT d + INTERVAL 1 DAY FROM untagged) AND b.hrv IS NOT NULL) AS hrv_without,
          (SELECT avg(b.rhr) FROM daily b WHERE b.d IN (SELECT d + INTERVAL 1 DAY FROM tagged) AND b.rhr IS NOT NULL) AS rhr_with,
          (SELECT avg(b.rhr) FROM daily b WHERE b.d IN (SELECT d + INTERVAL 1 DAY FROM untagged) AND b.rhr IS NOT NULL) AS rhr_without,
          (SELECT count(*) FROM tagged) AS n_with,
          (SELECT count(*) FROM untagged) AS n_without
    """
    row = con.execute(sql).fetchone()
    if not row or row[4] < 5 or row[5] < 5:
        return
    hrv_w, hrv_wo, rhr_w, rhr_wo, n_w, n_wo = row
    if hrv_w is None or hrv_wo is None or hrv_wo == 0:
        return

    hrv_diff_pct = (hrv_w - hrv_wo) / hrv_wo * 100
    rhr_diff = (rhr_w - rhr_wo) if rhr_w and rhr_wo else None

    direction = "ดีขึ้น" if hrv_diff_pct > 0 else "แย่ลง"
    hrv_msg = f"HRV วันถัดไป {direction} {abs(hrv_diff_pct):.0f}% ({hrv_w:.0f} vs {hrv_wo:.0f} ms)"
    rhr_msg = ""
    if rhr_diff is not None:
        rhr_dir = "สูงขึ้น" if rhr_diff > 0 else "ต่ำลง"
        rhr_msg = f" · RHR {rhr_dir} {abs(rhr_diff):.1f} bpm"

    impact = "positive" if hrv_diff_pct > 2 else "negative" if hrv_diff_pct < -2 else "neutral"

    results.append({
        "tag": tag_name,
        "label_th": label_th,
        "icon": icon,
        "n_with": int(n_w),
        "n_without": int(n_wo),
        "hrv_with": round(float(hrv_w), 1),
        "hrv_without": round(float(hrv_wo), 1),
        "hrv_diff_pct": round(hrv_diff_pct, 1),
        "rhr_with": round(float(rhr_w), 1) if rhr_w else None,
        "rhr_without": round(float(rhr_wo), 1) if rhr_wo else None,
        "rhr_diff": round(float(rhr_diff), 1) if rhr_diff else None,
        "impact": impact,
        "message_th": f"{icon} {label_th} ({n_w} ครั้ง): {hrv_msg}{rhr_msg}",
    })
