"""DuckDB-backed daily aggregations over parquet files.

DuckDB reads parquet files directly — no ETL step. We just point it at
the data/parquet directory and run SQL. All aggregations produce one
row per local day so the frontend can render time-series easily.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


class HealthStore:
    def __init__(self, parquet_dir: str | Path):
        self.parquet_dir = Path(parquet_dir)
        self.con = duckdb.connect(":memory:")
        # Let DuckDB handle timezone-aware timestamps cleanly.
        self.con.execute("SET TimeZone='Asia/Bangkok'")

    # ---- internal helpers -------------------------------------------------

    def _path(self, name: str) -> str:
        p = self.parquet_dir / f"{name}.parquet"
        return str(p).replace("\\", "/")

    def _exists(self, name: str) -> bool:
        return (self.parquet_dir / f"{name}.parquet").exists()

    # ---- public queries ---------------------------------------------------

    def daily_hrv(self, days: int = 90) -> list[dict[str, Any]]:
        """Nightly HRV — Whoop uses the last HRV reading during sleep, but
        Apple samples HRV sporadically (usually during Breathe/sleep). We
        take the daily median as a robust proxy."""
        if not self._exists("hrv_sdnn"):
            return []
        sql = f"""
            SELECT
                CAST(start AS DATE) AS day,
                median(value) AS hrv_ms,
                count(*) AS n
            FROM read_parquet('{self._path("hrv_sdnn")}')
            WHERE start >= current_date - INTERVAL {days} DAY
            GROUP BY 1
            ORDER BY 1
        """
        return self.con.execute(sql).fetchdf().to_dict("records")

    def daily_resting_hr(self, days: int = 90) -> list[dict[str, Any]]:
        if not self._exists("resting_heart_rate"):
            return []
        sql = f"""
            SELECT
                CAST(start AS DATE) AS day,
                avg(value) AS rhr_bpm
            FROM read_parquet('{self._path("resting_heart_rate")}')
            WHERE start >= current_date - INTERVAL {days} DAY
            GROUP BY 1
            ORDER BY 1
        """
        return self.con.execute(sql).fetchdf().to_dict("records")

    def daily_sleep(self, days: int = 90) -> list[dict[str, Any]]:
        """Sleep summary per night. Apple labels each interval as one of:
        InBed, AsleepCore, AsleepDeep, AsleepREM, Awake, AsleepUnspecified
        (legacy, pre-iOS 16).

        Two data-quality hazards handled here:

        1. Multiple sources (iPhone auto-detect, Apple Watch, 3rd-party apps)
           each write overlapping AsleepUnspecified intervals for the same
           night. Naive SUM double/triple-counts → "23.9 hr" type bugs.

        2. Modern nights (iOS 16+) have proper Core/Deep/REM stages. These
           are authoritative — any AsleepUnspecified on the same night is
           redundant coverage from another source and must be ignored.

        Strategy, per night:
          - If night has any modern stage (Core/Deep/REM): trust those only,
            drop AsleepUnspecified to prevent double-count.
          - Else (legacy / pre-iOS 16 night): take AsleepUnspecified and
            MERGE overlapping intervals (classic gaps-and-islands) before
            summing, so duplicate coverage from multiple sources collapses.

        Awake minutes come from Awake stage directly (rare in legacy data).
        """
        if not self._exists("sleep"):
            return []
        sql = f"""
            WITH raw AS (
              SELECT
                CAST("end" AS DATE) AS wake_day,
                stage,
                start,
                "end"
              FROM read_parquet('{self._path("sleep")}')
              WHERE "end" >= current_date - INTERVAL {days} DAY
            ),
            night_flag AS (
              SELECT wake_day,
                     MAX(CASE WHEN stage LIKE '%AsleepCore%'
                               OR stage LIKE '%AsleepDeep%'
                               OR stage LIKE '%AsleepREM%'
                              THEN 1 ELSE 0 END) AS has_modern
              FROM raw GROUP BY 1
            ),
            -- Modern-night path: sum stage durations directly (Apple Watch single source)
            modern AS (
              SELECT
                r.wake_day AS day,
                SUM(CASE WHEN stage LIKE '%AsleepCore%' OR stage LIKE '%AsleepDeep%' OR stage LIKE '%AsleepREM%'
                         THEN EXTRACT(EPOCH FROM (r."end" - r.start))/60.0 ELSE 0 END) AS asleep_min,
                SUM(CASE WHEN stage LIKE '%AsleepDeep%' THEN EXTRACT(EPOCH FROM (r."end" - r.start))/60.0 ELSE 0 END) AS deep_min,
                SUM(CASE WHEN stage LIKE '%AsleepREM%'  THEN EXTRACT(EPOCH FROM (r."end" - r.start))/60.0 ELSE 0 END) AS rem_min,
                SUM(CASE WHEN stage LIKE '%AsleepCore%' THEN EXTRACT(EPOCH FROM (r."end" - r.start))/60.0 ELSE 0 END) AS core_min,
                SUM(CASE WHEN stage LIKE '%Awake%'      THEN EXTRACT(EPOCH FROM (r."end" - r.start))/60.0 ELSE 0 END) AS awake_min
              FROM raw r JOIN night_flag nf USING (wake_day)
              WHERE nf.has_modern = 1
              GROUP BY r.wake_day
            ),
            -- Legacy-night path: only AsleepUnspecified (or old Asleep) intervals,
            -- then interval-merge to collapse overlapping coverage.
            legacy_raw AS (
              SELECT r.wake_day, r.start, r."end"
              FROM raw r JOIN night_flag nf USING (wake_day)
              WHERE nf.has_modern = 0 AND r.stage LIKE '%Asleep%'
            ),
            legacy_ordered AS (
              SELECT wake_day, start, "end",
                     MAX("end") OVER (
                       PARTITION BY wake_day ORDER BY start
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                     ) AS prev_max_end
              FROM legacy_raw
            ),
            legacy_grouped AS (
              SELECT wake_day, start, "end",
                     SUM(CASE WHEN prev_max_end IS NULL OR start > prev_max_end THEN 1 ELSE 0 END)
                       OVER (PARTITION BY wake_day ORDER BY start) AS island
              FROM legacy_ordered
            ),
            legacy_islands AS (
              SELECT wake_day, MIN(start) AS s, MAX("end") AS e
              FROM legacy_grouped
              GROUP BY wake_day, island
            ),
            legacy AS (
              SELECT wake_day AS day,
                     SUM(EXTRACT(EPOCH FROM (e - s))/60.0) AS asleep_min,
                     0.0 AS deep_min, 0.0 AS rem_min, 0.0 AS core_min, 0.0 AS awake_min
              FROM legacy_islands
              GROUP BY wake_day
            )
            SELECT * FROM modern
            UNION ALL
            SELECT * FROM legacy
            ORDER BY day
        """
        return self.con.execute(sql).fetchdf().to_dict("records")

    def daily_strain(self, days: int = 90) -> list[dict[str, Any]]:
        """Rough strain proxy: total active energy + time-in-HR-zones.
        Whoop's real strain is integral of HR above resting, scaled log —
        we'll approximate with active kcal for v1."""
        if not self._exists("active_energy_kcal"):
            return []
        sql = f"""
            SELECT
                CAST(start AS DATE) AS day,
                sum(value) AS active_kcal
            FROM read_parquet('{self._path("active_energy_kcal")}')
            WHERE start >= current_date - INTERVAL {days} DAY
            GROUP BY 1
            ORDER BY 1
        """
        return self.con.execute(sql).fetchdf().to_dict("records")

    def daily_rings(self, days: int = 90) -> list[dict[str, Any]]:
        """Activity rings from <ActivitySummary> — Move / Exercise / Stand
        with both actual and goal values. This is the exact data the
        Fitness app shows on its main screen."""
        if not self._exists("activity_rings"):
            return []
        sql = f"""
            SELECT
                day,
                active_kcal,
                active_kcal_goal,
                exercise_min,
                exercise_min_goal,
                stand_hours,
                stand_hours_goal,
                CASE WHEN active_kcal_goal > 0
                     THEN LEAST(1.0, active_kcal / active_kcal_goal) END AS move_pct,
                CASE WHEN exercise_min_goal > 0
                     THEN LEAST(1.0, exercise_min / exercise_min_goal) END AS exercise_pct,
                CASE WHEN stand_hours_goal > 0
                     THEN LEAST(1.0, stand_hours / stand_hours_goal) END AS stand_pct
            FROM read_parquet('{self._path("activity_rings")}')
            WHERE CAST(day AS DATE) >= current_date - INTERVAL {days} DAY
            ORDER BY day
        """
        return self.con.execute(sql).fetchdf().to_dict("records")

    def workouts(self, days: int = 90) -> list[dict[str, Any]]:
        """Individual workout sessions with HR / distance / kcal stats."""
        if not self._exists("workouts"):
            return []
        sql = f"""
            SELECT
                type,
                start,
                "end",
                duration_min,
                distance_km,
                active_kcal,
                hr_avg,
                hr_max
            FROM read_parquet('{self._path("workouts")}')
            WHERE start >= current_date - INTERVAL {days} DAY
            ORDER BY start DESC
        """
        return self.con.execute(sql).fetchdf().to_dict("records")

    def latest_snapshot(self) -> dict[str, Any]:
        """One-shot 'today' summary for the dashboard ring."""
        out: dict[str, Any] = {}
        if self._exists("hrv_sdnn"):
            row = self.con.execute(
                f"""SELECT value, start FROM read_parquet('{self._path("hrv_sdnn")}')
                    ORDER BY start DESC LIMIT 1"""
            ).fetchone()
            if row:
                out["latest_hrv_ms"] = row[0]
                out["latest_hrv_at"] = str(row[1])
        if self._exists("resting_heart_rate"):
            row = self.con.execute(
                f"""SELECT value, start FROM read_parquet('{self._path("resting_heart_rate")}')
                    ORDER BY start DESC LIMIT 1"""
            ).fetchone()
            if row:
                out["latest_rhr_bpm"] = row[0]
                out["latest_rhr_at"] = str(row[1])
        return out
