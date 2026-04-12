"""HR zone analysis per workout.

We join `heart_rate.parquet` with `workouts.parquet` on timestamp range
using DuckDB's range join, then bucket each HR sample into a zone based
on the user's personal max HR. Max HR is estimated from the top 0.1%
of all workout HR samples — within a couple bpm of true max for a
well-trained user with 1,500+ logged sessions.

Zones (% of max HR):
    Z1  50-60%   active recovery / warmup
    Z2  60-70%   aerobic base / fat burn
    Z3  70-80%   tempo / aerobic
    Z4  80-90%   threshold / lactate
    Z5  90-100%  VO2max / anaerobic
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


class ZoneAnalyzer:
    def __init__(self, parquet_dir: str | Path):
        self.pq = Path(parquet_dir)
        self.con = duckdb.connect(":memory:")
        self._max_hr: float | None = None

    def _p(self, name: str) -> str:
        return (self.pq / f"{name}.parquet").as_posix()

    def estimate_max_hr(self) -> float:
        """Top 0.1% of workout-window HR samples. Cached after first call."""
        if self._max_hr is not None:
            return self._max_hr

        sql = f"""
          SELECT quantile(h.value, 0.999) AS max_hr
          FROM read_parquet('{self._p("heart_rate")}') h
          JOIN read_parquet('{self._p("workouts")}') w
            ON h.start >= w.start AND h.start < w."end"
        """
        row = self.con.execute(sql).fetchone()
        self._max_hr = float(row[0]) if row and row[0] else 190.0
        return self._max_hr

    def zones_by_sport(self, days: int = 365 * 6) -> list[dict[str, Any]]:
        """Time in each HR zone per sport."""
        max_hr = self.estimate_max_hr()
        sql = f"""
          WITH joined AS (
            SELECT
              REPLACE(w.type, 'HKWorkoutActivityType', '') AS sport,
              h.value AS hr
            FROM read_parquet('{self._p("heart_rate")}') h
            JOIN read_parquet('{self._p("workouts")}') w
              ON h.start >= w.start AND h.start < w."end"
            WHERE w.start >= current_date - INTERVAL {days} DAY
          ),
          zoned AS (
            SELECT
              sport,
              CASE
                WHEN hr < {max_hr * 0.6} THEN 'Z1'
                WHEN hr < {max_hr * 0.7} THEN 'Z2'
                WHEN hr < {max_hr * 0.8} THEN 'Z3'
                WHEN hr < {max_hr * 0.9} THEN 'Z4'
                ELSE 'Z5'
              END AS zone
            FROM joined
          )
          SELECT
            sport,
            zone,
            count(*) AS samples,
            round(100.0 * count(*)
                   / sum(count(*)) OVER (PARTITION BY sport), 1) AS pct
          FROM zoned
          GROUP BY sport, zone
          ORDER BY sport, zone
        """
        return self.con.execute(sql).fetchdf().to_dict("records")

    def polarization_index(self, days: int = 365) -> list[dict[str, Any]]:
        """80/20 rule check: elite endurance athletes spend ~80% easy (Z1-Z2)
        and ~20% hard (Z4-Z5). 'Moderate trap' = too much time in Z3."""
        max_hr = self.estimate_max_hr()
        sql = f"""
          WITH joined AS (
            SELECT h.value AS hr
            FROM read_parquet('{self._p("heart_rate")}') h
            JOIN read_parquet('{self._p("workouts")}') w
              ON h.start >= w.start AND h.start < w."end"
            WHERE w.start >= current_date - INTERVAL {days} DAY
          ),
          buckets AS (
            SELECT
              CASE
                WHEN hr < {max_hr * 0.7} THEN 'easy'
                WHEN hr < {max_hr * 0.8} THEN 'moderate'
                ELSE 'hard'
              END AS bucket
            FROM joined
          )
          SELECT
            bucket,
            count(*) AS samples,
            round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
          FROM buckets
          GROUP BY 1
          ORDER BY
            CASE bucket WHEN 'easy' THEN 1 WHEN 'moderate' THEN 2 ELSE 3 END
        """
        return self.con.execute(sql).fetchdf().to_dict("records")

    def recent_workouts_with_zones(self, limit: int = 20) -> list[dict[str, Any]]:
        """Last N workouts with their per-session zone %."""
        max_hr = self.estimate_max_hr()
        sql = f"""
          WITH joined AS (
            SELECT
              w.start AS workout_start,
              REPLACE(w.type, 'HKWorkoutActivityType', '') AS sport,
              w.duration_min,
              CASE
                WHEN h.value < {max_hr * 0.6} THEN 'Z1'
                WHEN h.value < {max_hr * 0.7} THEN 'Z2'
                WHEN h.value < {max_hr * 0.8} THEN 'Z3'
                WHEN h.value < {max_hr * 0.9} THEN 'Z4'
                ELSE 'Z5'
              END AS zone
            FROM read_parquet('{self._p("workouts")}') w
            JOIN read_parquet('{self._p("heart_rate")}') h
              ON h.start >= w.start AND h.start < w."end"
          ),
          agg AS (
            SELECT
              workout_start,
              sport,
              duration_min,
              zone,
              count(*) AS n
            FROM joined
            GROUP BY 1, 2, 3, 4
          ),
          recent AS (
            SELECT DISTINCT workout_start, sport, duration_min
            FROM agg
            ORDER BY workout_start DESC
            LIMIT {limit}
          )
          SELECT
            r.workout_start,
            r.sport,
            r.duration_min,
            a.zone,
            round(100.0 * a.n / sum(a.n) OVER (PARTITION BY r.workout_start), 1) AS pct
          FROM recent r
          JOIN agg a USING (workout_start, sport, duration_min)
          ORDER BY r.workout_start DESC, a.zone
        """
        return self.con.execute(sql).fetchdf().to_dict("records")
