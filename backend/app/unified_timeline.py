"""Unified event timeline.

Merges every signal into one chronological stream so the frontend can
render a single timeline with color-coded event bands:

    - Anomaly episodes   (from illness.py)          → physiological flags
    - Data gaps          (from admissions.py)       → watch-off periods
    - HRV drift          (from pre_clinical.py)     → slow pre-clinical slides
    - Training blocks    (aggregated from workouts) → load phases
    - Known events       (user annotations)         → ground truth labels

Each entry has a `kind`, `start`, `end`, `severity`, and `context` dict.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from .queries import HealthStore
from .illness import detect_episodes
from .admissions import detect_admissions
from .pre_clinical import detect_drift


@dataclass
class TimelineEvent:
    kind: str            # anomaly | gap | drift | training | annotation
    start: str
    end: str
    days: int
    severity: str        # mild / moderate / severe / info
    label: str           # short human label
    context: dict        # free-form metadata


def _annotations_for_this_user() -> list[TimelineEvent]:
    """Ground-truth labels confirmed by the user in conversation on 2026-04-11."""
    return [
        TimelineEvent(
            kind="annotation",
            start="2023-08-11",
            end="2023-08-15",
            days=5,
            severity="severe",
            label="Dengue fever (ไข้เลือดออก) — admitted",
            context={"confirmed": True, "source": "user", "type": "admission"},
        ),
        TimelineEvent(
            kind="annotation",
            start="2024-01-24",
            end="2024-01-24",
            days=1,
            severity="moderate",
            label="LASIK eye exam (pre-op)",
            context={"confirmed": True, "source": "user", "type": "procedure"},
        ),
        TimelineEvent(
            kind="annotation",
            start="2024-02-25",
            end="2024-03-08",
            days=13,
            severity="severe",
            label="Flu A — outpatient",
            context={"confirmed": False, "source": "user_notes", "type": "illness"},
        ),
        TimelineEvent(
            kind="annotation",
            start="2025-07-25",
            end="2025-07-29",
            days=5,
            severity="severe",
            label="Flu B — admitted",
            context={"confirmed": True, "source": "user", "type": "admission"},
        ),
        TimelineEvent(
            kind="annotation",
            start="2025-08-27",
            end="2025-08-29",
            days=3,
            severity="moderate",
            label="Endoscopy with GA — outpatient",
            context={"confirmed": True, "source": "user", "type": "procedure"},
        ),
        TimelineEvent(
            kind="annotation",
            start="2025-09-16",
            end="2025-09-16",
            days=1,
            severity="severe",
            label="Abdominal pain — admitted 1 night",
            context={"confirmed": True, "source": "user", "type": "admission"},
        ),
    ]


def _training_blocks(parquet_dir: Path) -> list[TimelineEvent]:
    """Detect high/low training weeks using workout volume percentiles."""
    con = duckdb.connect(":memory:")
    wk_path = (parquet_dir / "workouts.parquet").as_posix()

    rows = con.execute(
        f"""
        WITH weekly AS (
          SELECT
            DATE_TRUNC('week', CAST(start AS DATE)) AS week,
            count(*) AS sessions,
            sum(duration_min) AS mins
          FROM read_parquet('{wk_path}')
          GROUP BY 1
        ),
        stats AS (
          SELECT avg(sessions) AS avg_s, stddev_pop(sessions) AS sd_s FROM weekly
        )
        SELECT week, sessions, mins,
               (sessions - stats.avg_s) / stats.sd_s AS z_sessions
        FROM weekly, stats
        ORDER BY week
    """
    ).fetchall()

    events: list[TimelineEvent] = []
    for week, sessions, mins, z in rows:
        week_str = str(week)[:10]
        end_day = (week + timedelta(days=6))
        end_str = str(end_day)[:10]
        if z is None:
            continue
        if z >= 1.5:
            events.append(
                TimelineEvent(
                    kind="training",
                    start=week_str,
                    end=end_str,
                    days=7,
                    severity="info",
                    label=f"High load week — {int(sessions)} sessions",
                    context={
                        "sessions": int(sessions),
                        "minutes": int(mins or 0),
                        "z": round(float(z), 2),
                        "direction": "peak",
                    },
                )
            )
        elif z <= -1.5:
            events.append(
                TimelineEvent(
                    kind="training",
                    start=week_str,
                    end=end_str,
                    days=7,
                    severity="info",
                    label=f"Rest / low week — {int(sessions)} sessions",
                    context={
                        "sessions": int(sessions),
                        "minutes": int(mins or 0),
                        "z": round(float(z), 2),
                        "direction": "valley",
                    },
                )
            )
    return events


def build_unified_timeline(parquet_dir: str | Path) -> list[dict[str, Any]]:
    parquet_dir = Path(parquet_dir)
    store = HealthStore(parquet_dir)

    events: list[TimelineEvent] = []

    # 1. Anomaly episodes
    ill = detect_episodes(store, days=365 * 6)
    for ep in ill["episodes"]:
        if ep["severity"] == "mild":
            continue  # too noisy for the timeline; keep severe+moderate only
        events.append(
            TimelineEvent(
                kind="anomaly",
                start=ep["start"][:10],
                end=ep["end"][:10],
                days=ep["days"],
                severity=ep["severity"],
                label=f"Anomaly ({ep['severity']}) — RHR z={ep['peak_rhr_z']} HRV z={ep['trough_hrv_z']}",
                context={
                    "peak_rhr_bpm": ep["peak_rhr_bpm"],
                    "trough_hrv_ms": ep["trough_hrv_ms"],
                    "peak_rhr_z": ep["peak_rhr_z"],
                    "trough_hrv_z": ep["trough_hrv_z"],
                },
            )
        )

    # 2. Data gaps with flanking anomaly (admission candidates)
    admissions = detect_admissions(
        parquet_dir, min_gap_days=1, max_gap_days=14
    )
    for a in admissions:
        # Skip pure noise: require at least ONE side of anomaly for timeline
        pre_bad = a.pre_anomaly and (
            (a.pre_anomaly.get("rhr_z") or 0) >= 1.5
            or (a.pre_anomaly.get("hrv_z") or 0) <= -1.5
        )
        post_bad = a.post_anomaly and (
            (a.post_anomaly.get("rhr_z") or 0) >= 1.5
            or (a.post_anomaly.get("hrv_z") or 0) <= -1.5
        )
        if not (pre_bad or post_bad):
            continue
        sev = "severe" if (pre_bad and post_bad and a.gap_length >= 2) else "moderate"
        events.append(
            TimelineEvent(
                kind="gap",
                start=a.gap_start,
                end=a.gap_end,
                days=a.gap_length,
                severity=sev,
                label=f"Data gap {a.gap_length}d (flanked by anomaly)",
                context={
                    "weekday_gap_days": a.weekday_gap_days,
                    "score": a.score,
                    "pre": a.pre_anomaly,
                    "post": a.post_anomaly,
                },
            )
        )

    # 3. HRV drift periods
    drifts = detect_drift(
        parquet_dir, rolling_days=7, min_drift_days=3, depth_sigma_threshold=0.7
    )
    for d in drifts:
        sev = "moderate" if d.depth_sigma >= 1.0 else "mild"
        events.append(
            TimelineEvent(
                kind="drift",
                start=d.start,
                end=d.end,
                days=d.days,
                severity=sev,
                label=f"HRV drift {d.depth_sigma:.1f}σ below baseline ({d.days}d)",
                context={
                    "median_hrv": d.median_hrv,
                    "baseline_hrv": d.baseline_hrv,
                    "min_hrv": d.min_hrv,
                    "depth_sigma": d.depth_sigma,
                },
            )
        )

    # 4. Training blocks
    events.extend(_training_blocks(parquet_dir))

    # 5. Annotations
    events.extend(_annotations_for_this_user())

    events.sort(key=lambda e: e.start)
    return [asdict(e) for e in events]
