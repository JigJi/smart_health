"""Pre-clinical early-warning detector.

Sep 2025 ground truth: user was admitted for severe abdominal pain on
Sep 16, but HRV had been drifting downward for ~8 days prior (Sep 8-15
readings: 21, 21, 26, 18). The body knew something was wrong before
the pain crossed the 'go to hospital' threshold.

We detect these drift periods by computing a 7-day rolling median of
HRV and flagging stretches where it sits >= 1σ below the 60-day
personal baseline for N+ consecutive days. This is a DIFFERENT signal
from the per-day anomaly detector — it catches the slow slide, not
the acute crash.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import duckdb


@dataclass
class DriftPeriod:
    start: str          # first day of the drift window
    end: str            # last day
    days: int
    median_hrv: float   # median HRV across the window
    baseline_hrv: float # 60-day baseline at start
    depth_sigma: float  # how far below baseline (in σ)
    min_hrv: float      # worst single day


def detect_drift(
    parquet_dir: str | Path,
    rolling_days: int = 7,
    min_drift_days: int = 4,
    depth_sigma_threshold: float = 1.0,
    baseline_days: int = 60,
) -> list[DriftPeriod]:
    """Find stretches where 7-day rolling median HRV sits at least 1σ
    below a rolling 60-day baseline for 4+ consecutive days."""
    parquet_dir = Path(parquet_dir)
    con = duckdb.connect(":memory:")

    hrv_path = (parquet_dir / "hrv_sdnn.parquet").as_posix()

    # Daily median HRV as a dense series (one row per day with data).
    daily_sql = f"""
        SELECT
            CAST(start AS DATE) AS day,
            median(value) AS hrv
        FROM read_parquet('{hrv_path}')
        GROUP BY 1
        ORDER BY 1
    """
    rows = con.execute(daily_sql).fetchall()
    if len(rows) < baseline_days + rolling_days:
        return []

    days = [r[0] for r in rows]
    vals = [float(r[1]) for r in rows]

    # Compute for each day: 7-day rolling median + 60-day baseline mean/std
    # using prior data only (no leakage).
    drift_flags: list[tuple[int, float, float, float]] = []
    # (index, rolling_median, baseline_mean, depth_in_sigma)

    for i in range(rolling_days, len(vals)):
        window = vals[max(0, i - rolling_days + 1) : i + 1]
        rolling_med = sorted(window)[len(window) // 2]

        # 60-day baseline over PRIOR data only
        base_start = max(0, i - baseline_days)
        base = vals[base_start : i - rolling_days]
        if len(base) < 14:
            continue
        m = sum(base) / len(base)
        var = sum((x - m) ** 2 for x in base) / len(base)
        s = var ** 0.5 or 1.0
        depth = (m - rolling_med) / s   # positive = below baseline
        drift_flags.append((i, rolling_med, m, depth))

    # Collapse consecutive flagged days into drift periods.
    periods: list[DriftPeriod] = []
    cur: list[tuple[int, float, float, float]] = []

    def _close() -> None:
        if len(cur) < min_drift_days:
            return
        idxs = [c[0] for c in cur]
        start_day = days[idxs[0]]
        end_day = days[idxs[-1]]
        meds = [c[1] for c in cur]
        depth_max = max(c[3] for c in cur)
        base_at_start = cur[0][2]
        periods.append(
            DriftPeriod(
                start=str(start_day),
                end=str(end_day),
                days=len(cur),
                median_hrv=round(sum(meds) / len(meds), 1),
                baseline_hrv=round(base_at_start, 1),
                depth_sigma=round(depth_max, 2),
                min_hrv=round(min(vals[i] for i in idxs), 1),
            )
        )

    for flag in drift_flags:
        if flag[3] >= depth_sigma_threshold:
            cur.append(flag)
        else:
            _close()
            cur = []
    _close()

    # Sort by severity (deepest drift first)
    periods.sort(key=lambda p: -p.depth_sigma)
    return periods


def detect_drift_dict(parquet_dir: str | Path, **kwargs) -> list[dict[str, Any]]:
    return [asdict(p) for p in detect_drift(parquet_dir, **kwargs)]
