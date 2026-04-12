"""Hospital admission detector — gap-based.

The user takes their Watch off BEFORE admission, so a hospital stay does
NOT look like a physiological anomaly — it looks like a **hole** in the
data, usually flanked by anomaly signals (body going downhill → admit,
then body recovering → go home → put Watch back on).

Signature:
    1. Multi-day HR data gap (≥ min_gap_days)
    2. Gap is unusual — not matching user's normal weekday wear pattern
    3. Flanked by anomaly on at least ONE side (pre-gap OR post-gap)

We rank candidates by: gap length + flanking anomaly severity + day-of-week
unusualness (Tuesday-Thursday gaps are more suspicious than Monday/Friday
because user is a weekday-daytime wearer).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb


@dataclass
class Admission:
    gap_start: str         # first missing day
    gap_end: str           # last missing day
    gap_length: int        # total missing days
    weekday_gap_days: int  # missing days that fall on a weekday
    pre_anomaly: dict | None
    post_anomaly: dict | None
    score: float


def _anomaly_snapshot(
    con: duckdb.DuckDBPyConnection,
    parquet_dir: Path,
    window_start: date,
    window_end: date,
) -> dict | None:
    """Return the strongest anomaly signal (RHR/HRV z vs 60-day baseline)
    observed in [window_start, window_end]."""
    rhr_path = (parquet_dir / "resting_heart_rate.parquet").as_posix()
    hrv_path = (parquet_dir / "hrv_sdnn.parquet").as_posix()

    result: dict[str, float | str] = {}

    # RHR peak z
    sql = f"""
        WITH base AS (
            SELECT value FROM read_parquet('{rhr_path}')
            WHERE CAST(start AS DATE) BETWEEN
                  DATE '{window_start}' - INTERVAL 60 DAY AND DATE '{window_start}' - INTERVAL 1 DAY
        ),
        target AS (
            SELECT max(value) AS peak, min(CAST(start AS DATE)) AS d
            FROM read_parquet('{rhr_path}')
            WHERE CAST(start AS DATE) BETWEEN DATE '{window_start}' AND DATE '{window_end}'
        ),
        stats AS (
            SELECT avg(value) AS m, stddev_pop(value) AS s, count(*) AS n FROM base
        )
        SELECT target.peak, target.d, stats.m, stats.s, stats.n
        FROM target, stats
    """
    row = con.execute(sql).fetchone()
    if row and row[0] is not None and row[2] is not None and row[3] and row[4] >= 7:
        z = (row[0] - row[2]) / row[3]
        result["rhr_peak"] = float(row[0])
        result["rhr_z"] = round(z, 2)
        result["rhr_day"] = str(row[1])

    # HRV trough z
    sql = f"""
        WITH base AS (
            SELECT value FROM read_parquet('{hrv_path}')
            WHERE CAST(start AS DATE) BETWEEN
                  DATE '{window_start}' - INTERVAL 60 DAY AND DATE '{window_start}' - INTERVAL 1 DAY
        ),
        target AS (
            SELECT min(value) AS trough, min(CAST(start AS DATE)) AS d
            FROM read_parquet('{hrv_path}')
            WHERE CAST(start AS DATE) BETWEEN DATE '{window_start}' AND DATE '{window_end}'
        ),
        stats AS (
            SELECT avg(value) AS m, stddev_pop(value) AS s, count(*) AS n FROM base
        )
        SELECT target.trough, target.d, stats.m, stats.s, stats.n
        FROM target, stats
    """
    row = con.execute(sql).fetchone()
    if row and row[0] is not None and row[2] is not None and row[3] and row[4] >= 7:
        z = (row[0] - row[2]) / row[3]
        result["hrv_trough"] = float(row[0])
        result["hrv_z"] = round(z, 2)
        result["hrv_day"] = str(row[1])

    return result or None


def detect_admissions(
    parquet_dir: str | Path,
    min_gap_days: int = 1,
    max_gap_days: int = 21,
) -> list[Admission]:
    """Find multi-day HR data gaps that look like hospital admissions.

    A gap is a run of consecutive days with ZERO heart rate samples.
    The user takes the Watch off on weekends, so 2-day Sat/Sun gaps are
    normal and filtered out. We require ≥3 days by default.
    """
    parquet_dir = Path(parquet_dir)
    con = duckdb.connect(":memory:")

    hr_path = (parquet_dir / "heart_rate.parquet").as_posix()

    # Days that have ANY HR data — this is "Watch was worn at least part of the day"
    worn_sql = f"""
        SELECT DISTINCT CAST(start AS DATE) AS d
        FROM read_parquet('{hr_path}')
        ORDER BY 1
    """
    worn = [r[0] for r in con.execute(worn_sql).fetchall()]
    if not worn:
        return []

    worn_set = set(worn)
    first = worn[0]
    last = worn[-1]

    # Walk every day in the range, collecting runs of consecutive missing days.
    gaps: list[tuple[date, date]] = []
    run_start: date | None = None
    d = first
    while d <= last:
        if d not in worn_set:
            if run_start is None:
                run_start = d
            last_missing = d
        else:
            if run_start is not None:
                gaps.append((run_start, last_missing))
                run_start = None
        d += timedelta(days=1)
    if run_start is not None:
        gaps.append((run_start, last_missing))

    admissions: list[Admission] = []
    for g_start, g_end in gaps:
        length = (g_end - g_start).days + 1
        if length < min_gap_days or length > max_gap_days:
            continue

        # Count weekday days (Mon=0..Sun=6). If the gap is entirely Sat-Sun,
        # it's just a normal weekend — skip. Must have at least 1 weekday.
        weekday_count = 0
        d = g_start
        while d <= g_end:
            if d.weekday() < 5:
                weekday_count += 1
            d += timedelta(days=1)
        if weekday_count == 0:
            continue

        pre = _anomaly_snapshot(
            con, parquet_dir, g_start - timedelta(days=10), g_start - timedelta(days=1)
        )
        post = _anomaly_snapshot(
            con, parquet_dir, g_end + timedelta(days=1), g_end + timedelta(days=10)
        )

        # Scoring:
        #   + weekday gap days (each one is ~1 point)
        #   + flanking anomaly severity (peak z-scores)
        #   + bonus if BOTH sides show anomaly
        score = float(weekday_count)
        flank_sides = 0
        for side in (pre, post):
            if not side:
                continue
            anom = False
            if side.get("rhr_z") is not None and side["rhr_z"] >= 1.5:
                score += min(side["rhr_z"], 5)
                anom = True
            if side.get("hrv_z") is not None and side["hrv_z"] <= -1.5:
                score += min(-side["hrv_z"], 5)
                anom = True
            if anom:
                flank_sides += 1
        if flank_sides == 2:
            score += 3  # both-sides bonus

        admissions.append(
            Admission(
                gap_start=str(g_start),
                gap_end=str(g_end),
                gap_length=length,
                weekday_gap_days=weekday_count,
                pre_anomaly=pre,
                post_anomaly=post,
                score=round(score, 1),
            )
        )

    admissions.sort(key=lambda a: -a.score)
    return admissions


def detect_admissions_dict(parquet_dir: str | Path, **kwargs) -> list[dict[str, Any]]:
    return [asdict(a) for a in detect_admissions(parquet_dir, **kwargs)]
