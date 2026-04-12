"""Multi-year fitness timeline.

Aggregates rhr / hrv / walking-HR / vo2 / training-volume into monthly
buckets and returns a long trend series. This is the 'Spotify Wrapped
for your heart' view — years of change at a glance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


class Timeline:
    def __init__(self, parquet_dir: str | Path):
        self.pq = Path(parquet_dir)
        self.con = duckdb.connect(":memory:")

    def _p(self, name: str) -> str:
        return (self.pq / f"{name}.parquet").as_posix()

    def _exists(self, name: str) -> bool:
        return (self.pq / f"{name}.parquet").exists()

    def monthly(self) -> list[dict[str, Any]]:
        """One row per month with every metric we can compute.

        We LEFT JOIN onto the month spine so gaps become NULLs rather
        than missing rows — makes the frontend chart behave cleanly.
        """
        spine = """
            WITH spine AS (
                SELECT DISTINCT DATE_TRUNC('month', day) AS month
                FROM (
                    SELECT day FROM (
                        SELECT CAST(start AS DATE) AS day FROM read_parquet('{rhr}')
                        UNION ALL
                        SELECT CAST(start AS DATE) FROM read_parquet('{hrv}')
                    )
                )
            )
        """

        rhr = self._p("resting_heart_rate") if self._exists("resting_heart_rate") else None
        hrv = self._p("hrv_sdnn") if self._exists("hrv_sdnn") else None
        if not rhr or not hrv:
            return []

        # Monthly aggregates — each metric as its own CTE, then LEFT JOIN.
        sql = f"""
        WITH spine AS (
          SELECT DISTINCT DATE_TRUNC('month', CAST(start AS DATE)) AS month
          FROM read_parquet('{rhr}')
          UNION
          SELECT DISTINCT DATE_TRUNC('month', CAST(start AS DATE))
          FROM read_parquet('{hrv}')
        ),
        rhr_m AS (
          SELECT DATE_TRUNC('month', CAST(start AS DATE)) AS month,
                 median(value) AS rhr_median,
                 count(*) AS rhr_n
          FROM read_parquet('{rhr}')
          GROUP BY 1
        ),
        hrv_m AS (
          SELECT DATE_TRUNC('month', CAST(start AS DATE)) AS month,
                 median(value) AS hrv_median,
                 count(*) AS hrv_n
          FROM read_parquet('{hrv}')
          GROUP BY 1
        )
        """

        parts = ["spine", "rhr_m", "hrv_m"]
        select_cols = [
            "s.month",
            "rhr_m.rhr_median",
            "rhr_m.rhr_n",
            "hrv_m.hrv_median",
            "hrv_m.hrv_n",
        ]

        if self._exists("vo2_max"):
            sql += f""",
            vo2_m AS (
              SELECT DATE_TRUNC('month', CAST(start AS DATE)) AS month,
                     avg(value) AS vo2_mean
              FROM read_parquet('{self._p("vo2_max")}')
              GROUP BY 1
            )
            """
            parts.append("vo2_m")
            select_cols.append("vo2_m.vo2_mean")

        if self._exists("walking_hr_avg"):
            sql += f""",
            wh_m AS (
              SELECT DATE_TRUNC('month', CAST(start AS DATE)) AS month,
                     avg(value) AS walking_hr
              FROM read_parquet('{self._p("walking_hr_avg")}')
              GROUP BY 1
            )
            """
            parts.append("wh_m")
            select_cols.append("wh_m.walking_hr")

        if self._exists("exercise_minutes"):
            sql += f""",
            ex_m AS (
              SELECT DATE_TRUNC('month', CAST(start AS DATE)) AS month,
                     sum(value) AS exercise_min_total
              FROM read_parquet('{self._p("exercise_minutes")}')
              GROUP BY 1
            )
            """
            parts.append("ex_m")
            select_cols.append("ex_m.exercise_min_total")

        if self._exists("workouts"):
            sql += f""",
            wk_m AS (
              SELECT DATE_TRUNC('month', CAST(start AS DATE)) AS month,
                     count(*) AS workout_count,
                     sum(duration_min) AS workout_min
              FROM read_parquet('{self._p("workouts")}')
              GROUP BY 1
            )
            """
            parts.append("wk_m")
            select_cols += ["wk_m.workout_count", "wk_m.workout_min"]

        sql += "SELECT " + ",\n  ".join(select_cols) + "\n"
        sql += "FROM spine s\n"
        for p in parts[1:]:
            sql += f"LEFT JOIN {p} USING (month)\n"
        sql += "ORDER BY s.month\n"

        return self.con.execute(sql).fetchdf().to_dict("records")

    def yearly_summary(self) -> list[dict[str, Any]]:
        """High-level year-over-year table for the 'Wrapped' header."""
        sql = f"""
          SELECT
            EXTRACT(YEAR FROM start) AS year,
            count(*) AS workouts,
            round(sum(duration_min) / 60, 1) AS hours,
            round(sum(active_kcal)) AS active_kcal,
            round(avg(hr_avg), 1) AS avg_hr,
            round(avg(hr_max), 1) AS avg_hr_max
          FROM read_parquet('{self._p("workouts")}')
          WHERE hr_avg IS NOT NULL OR hr_max IS NOT NULL OR active_kcal IS NOT NULL
             OR duration_min > 0
          GROUP BY 1
          ORDER BY 1
        """
        return self.con.execute(sql).fetchdf().to_dict("records")

    def sport_breakdown(self) -> list[dict[str, Any]]:
        """Which sports dominate each year — is there a shift?"""
        sql = f"""
          SELECT
            EXTRACT(YEAR FROM start) AS year,
            REPLACE(type, 'HKWorkoutActivityType', '') AS sport,
            count(*) AS sessions,
            round(sum(duration_min) / 60, 1) AS hours
          FROM read_parquet('{self._p("workouts")}')
          GROUP BY 1, 2
          ORDER BY 1, sessions DESC
        """
        return self.con.execute(sql).fetchdf().to_dict("records")
