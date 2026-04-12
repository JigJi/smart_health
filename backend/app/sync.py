"""Health data sync receiver.

Accepts incremental health data from any source (Apple Shortcuts,
Health Auto Export app, future iOS app) in a simple JSON format,
appends to existing parquet files so all analytics stay up to date.

Expected payload:
{
  "heart_rate": [{"time": "2026-04-12T08:00:00+0700", "value": 72}],
  "hrv": [{"time": "...", "value": 35.5}],
  "resting_heart_rate": [{"time": "...", "value": 65}],
  "workouts": [{
    "type": "TraditionalStrengthTraining",
    "start": "...", "end": "...",
    "duration_min": 55, "hr_avg": 120, "hr_max": 155
  }],
  "steps": [{"time": "...", "value": 1234}]
}

All fields are optional — send whatever you have.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


# Map from sync field names to parquet file + column config
METRIC_MAP = {
    "heart_rate": {
        "file": "heart_rate.parquet",
        "columns": {"time": "start", "value": "value"},
        "extra": {"unit": "count/min", "source": "sync"},
    },
    "hrv": {
        "file": "hrv_sdnn.parquet",
        "columns": {"time": "start", "value": "value"},
        "extra": {"unit": "ms", "source": "sync"},
    },
    "resting_heart_rate": {
        "file": "resting_heart_rate.parquet",
        "columns": {"time": "start", "value": "value"},
        "extra": {"unit": "count/min", "source": "sync"},
    },
    "spo2": {
        "file": "spo2.parquet",
        "columns": {"time": "start", "value": "value"},
        "extra": {"unit": "%", "source": "sync"},
    },
    "steps": {
        "file": "steps.parquet",
        "columns": {"time": "start", "value": "value"},
        "extra": {"unit": "count", "source": "sync"},
    },
    "active_energy": {
        "file": "active_energy_kcal.parquet",
        "columns": {"time": "start", "value": "value"},
        "extra": {"unit": "kcal", "source": "sync"},
    },
}


def _parse_time(s: str) -> datetime:
    """Parse various time formats Apple might send."""
    for fmt in [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(s)


def receive_sync(parquet_dir: str | Path, payload: dict[str, Any]) -> dict[str, int]:
    """Append incoming data to existing parquet files.

    Returns dict of metric_name -> rows_added.
    """
    parquet_dir = Path(parquet_dir)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, int] = {}

    # Process simple metrics (time+value pairs)
    for field, config in METRIC_MAP.items():
        samples = payload.get(field, [])
        if not samples:
            continue

        rows = []
        for s in samples:
            t = s.get("time") or s.get("start") or s.get("date")
            v = s.get("value")
            if t is None or v is None:
                continue
            row = {
                "start": _parse_time(str(t)),
                "end": _parse_time(str(t)),
                "value": float(v),
            }
            row.update(config["extra"])
            rows.append(row)

        if rows:
            _append_parquet(parquet_dir / config["file"], rows)
            result[field] = len(rows)

    # Process workouts separately (different schema)
    workouts = payload.get("workouts", [])
    if workouts:
        rows = []
        for w in workouts:
            start = w.get("start")
            end = w.get("end")
            if not start:
                continue
            wtype = w.get("type", "Unknown")
            if not wtype.startswith("HKWorkoutActivityType"):
                wtype = f"HKWorkoutActivityType{wtype}"
            rows.append({
                "type": wtype,
                "start": _parse_time(str(start)),
                "end": _parse_time(str(end)) if end else _parse_time(str(start)),
                "duration_min": float(w.get("duration_min", 0)),
                "distance_km": w.get("distance_km"),
                "active_kcal": w.get("active_kcal"),
                "hr_avg": w.get("hr_avg"),
                "hr_max": w.get("hr_max"),
                "source": "sync",
            })
        if rows:
            _append_parquet(parquet_dir / "workouts.parquet", rows)
            result["workouts"] = len(rows)

    return result


def _append_parquet(path: Path, rows: list[dict]) -> None:
    """Append rows to existing parquet file (or create new one).

    Deduplicates on (start, value) to handle repeated syncs safely.
    """
    new_df = pd.DataFrame(rows)

    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_df], ignore_index=True)

        # Deduplicate: same start time + same value = duplicate
        if "value" in combined.columns:
            combined = combined.drop_duplicates(
                subset=["start", "value"], keep="first"
            )
        elif "type" in combined.columns:
            combined = combined.drop_duplicates(
                subset=["start", "type"], keep="first"
            )

        combined.to_parquet(path, index=False)
    else:
        new_df.to_parquet(path, index=False)


def generate_shortcut_url(backend_url: str) -> str:
    """Generate the URL the Apple Shortcut should POST to."""
    return f"{backend_url}/sync"
