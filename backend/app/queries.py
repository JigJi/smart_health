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
        InBed, AsleepCore, AsleepDeep, AsleepREM, Awake, Asleep (old API).
        We sum durations and attribute the night to the wake-up date."""
        if not self._exists("sleep"):
            return []
        sql = f"""
            WITH intervals AS (
              SELECT
                CAST("end" AS DATE) AS wake_day,
                stage,
                EXTRACT(EPOCH FROM ("end" - start)) / 60.0 AS minutes
              FROM read_parquet('{self._path("sleep")}')
              WHERE "end" >= current_date - INTERVAL {days} DAY
            )
            SELECT
              wake_day AS day,
              SUM(CASE WHEN stage LIKE '%Asleep%' THEN minutes ELSE 0 END) AS asleep_min,
              SUM(CASE WHEN stage LIKE '%Deep%'   THEN minutes ELSE 0 END) AS deep_min,
              SUM(CASE WHEN stage LIKE '%REM%'    THEN minutes ELSE 0 END) AS rem_min,
              SUM(CASE WHEN stage LIKE '%Core%'   THEN minutes ELSE 0 END) AS core_min,
              SUM(CASE WHEN stage LIKE '%Awake%'  THEN minutes ELSE 0 END) AS awake_min
            FROM intervals
            GROUP BY 1
            ORDER BY 1
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
