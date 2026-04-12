"""Apple Health export.xml streaming parser → Parquet.

Apple Health exports a single huge XML with <Record>, <Workout>,
<ActivitySummary> elements. We stream-parse to keep memory bounded,
bucket records by HKQuantityTypeIdentifier, and write one Parquet
per metric type for fast columnar queries via DuckDB.
"""

from __future__ import annotations

import os
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pandas as pd
from lxml import etree


# Metrics we care about for a Whoop/Bevel-style app.
# Mapping: HK identifier → friendly column name
METRICS_OF_INTEREST: dict[str, str] = {
    "HKQuantityTypeIdentifierHeartRate": "heart_rate",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_heart_rate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv_sdnn",
    "HKQuantityTypeIdentifierWalkingHeartRateAverage": "walking_hr_avg",
    "HKQuantityTypeIdentifierOxygenSaturation": "spo2",
    "HKQuantityTypeIdentifierRespiratoryRate": "respiratory_rate",
    "HKQuantityTypeIdentifierBodyTemperature": "body_temperature",
    "HKQuantityTypeIdentifierAppleSleepingWristTemperature": "wrist_temperature",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "active_energy_kcal",
    "HKQuantityTypeIdentifierBasalEnergyBurned": "basal_energy_kcal",
    "HKQuantityTypeIdentifierStepCount": "steps",
    "HKQuantityTypeIdentifierDistanceWalkingRunning": "distance_m",
    "HKQuantityTypeIdentifierVO2Max": "vo2_max",
    "HKQuantityTypeIdentifierAppleStandTime": "stand_minutes",
    "HKQuantityTypeIdentifierAppleExerciseTime": "exercise_minutes",
}

SLEEP_TYPE = "HKCategoryTypeIdentifierSleepAnalysis"


@dataclass
class ParseStats:
    record_count: int = 0
    workout_count: int = 0
    sleep_count: int = 0
    activity_day_count: int = 0
    metrics_written: dict[str, int] = None

    def __post_init__(self) -> None:
        if self.metrics_written is None:
            self.metrics_written = {}


def _open_export_xml(source: Path) -> tuple[Iterator[bytes], object | None]:
    """Return a file-like for export.xml whether `source` is the xml itself
    or the export.zip Apple gives you. Returns (fileobj, owning_zip_or_None)."""
    source = Path(source)
    if source.suffix == ".zip":
        zf = zipfile.ZipFile(source)
        # Apple's structure: apple_health_export/export.xml
        member = next(
            n for n in zf.namelist() if n.endswith("export.xml") and "export_cda" not in n
        )
        return zf.open(member), zf
    return open(source, "rb"), None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # Apple format: "2025-01-15 06:30:00 +0700"
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")


def parse_export(
    source: str | Path,
    out_dir: str | Path,
) -> ParseStats:
    """Stream-parse Apple Health export and write per-metric Parquet files.

    Output layout:
        out_dir/heart_rate.parquet
        out_dir/hrv_sdnn.parquet
        ...
        out_dir/sleep.parquet
        out_dir/workouts.parquet
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fileobj, owning = _open_export_xml(Path(source))
    stats = ParseStats()

    # Buffer rows in memory by metric name. For very large exports we could
    # flush per-N rows, but per-metric these stay reasonable (HR is the worst
    # at ~minute-level resolution → ~500k rows/year, fine in RAM).
    buckets: dict[str, list[dict]] = defaultdict(list)
    sleep_rows: list[dict] = []
    workout_rows: list[dict] = []
    activity_rows: list[dict] = []

    try:
        context = etree.iterparse(
            fileobj,
            events=("end",),
            tag=("Record", "Workout", "ActivitySummary"),
            recover=True,
            huge_tree=True,
        )

        for _, elem in context:
            if elem.tag == "Record":
                hk_type = elem.get("type", "")
                start = _parse_dt(elem.get("startDate"))
                end = _parse_dt(elem.get("endDate"))
                source_name = elem.get("sourceName")

                if hk_type in METRICS_OF_INTEREST:
                    col = METRICS_OF_INTEREST[hk_type]
                    val = elem.get("value")
                    try:
                        val_f = float(val) if val is not None else None
                    except ValueError:
                        val_f = None
                    buckets[col].append(
                        {
                            "start": start,
                            "end": end,
                            "value": val_f,
                            "unit": elem.get("unit"),
                            "source": source_name,
                        }
                    )
                    stats.record_count += 1

                elif hk_type == SLEEP_TYPE:
                    sleep_rows.append(
                        {
                            "start": start,
                            "end": end,
                            "stage": elem.get("value"),
                            "source": source_name,
                        }
                    )
                    stats.sleep_count += 1

            elif elem.tag == "Workout":
                # Newer exports put avg/max HR, distance, kcal in
                # <WorkoutStatistics type="..."> children instead of attrs.
                wstats: dict[str, float] = {}
                for child in elem.iterchildren("WorkoutStatistics"):
                    t = child.get("type", "")
                    avg = child.get("average")
                    sumv = child.get("sum")
                    maxv = child.get("maximum")
                    if t.endswith("HeartRate"):
                        if avg:
                            wstats["hr_avg"] = float(avg)
                        if maxv:
                            wstats["hr_max"] = float(maxv)
                    elif t.endswith("ActiveEnergyBurned") and sumv:
                        wstats["active_kcal"] = float(sumv)
                    elif t.endswith("DistanceWalkingRunning") and sumv:
                        wstats["distance_km"] = float(sumv)
                    elif t.endswith("DistanceCycling") and sumv:
                        wstats["distance_km"] = float(sumv)

                # Older format: duration & totals live on the element itself.
                legacy_dist = elem.get("totalDistance")
                legacy_kcal = elem.get("totalEnergyBurned")

                workout_rows.append(
                    {
                        "type": elem.get("workoutActivityType"),
                        "start": _parse_dt(elem.get("startDate")),
                        "end": _parse_dt(elem.get("endDate")),
                        "duration_min": float(elem.get("duration") or 0),
                        "distance_km": wstats.get(
                            "distance_km",
                            float(legacy_dist) if legacy_dist else None,
                        ),
                        "active_kcal": wstats.get(
                            "active_kcal",
                            float(legacy_kcal) if legacy_kcal else None,
                        ),
                        "hr_avg": wstats.get("hr_avg"),
                        "hr_max": wstats.get("hr_max"),
                        "source": elem.get("sourceName"),
                    }
                )
                stats.workout_count += 1

            elif elem.tag == "ActivitySummary":
                # Daily ring data — this is exactly what the Fitness app shows.
                activity_rows.append(
                    {
                        "day": elem.get("dateComponents"),
                        "active_kcal": float(elem.get("activeEnergyBurned") or 0),
                        "active_kcal_goal": float(
                            elem.get("activeEnergyBurnedGoal") or 0
                        ),
                        "exercise_min": float(
                            elem.get("appleExerciseTime") or 0
                        ),
                        "exercise_min_goal": float(
                            elem.get("appleExerciseTimeGoal") or 0
                        ),
                        "stand_hours": float(elem.get("appleStandHours") or 0),
                        "stand_hours_goal": float(
                            elem.get("appleStandHoursGoal") or 0
                        ),
                    }
                )
                stats.activity_day_count += 1

            # Drop refs so memory stays bounded.
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

        for col, rows in buckets.items():
            df = pd.DataFrame(rows)
            path = out_dir / f"{col}.parquet"
            df.to_parquet(path, index=False)
            stats.metrics_written[col] = len(df)

        if sleep_rows:
            pd.DataFrame(sleep_rows).to_parquet(out_dir / "sleep.parquet", index=False)
            stats.metrics_written["sleep"] = len(sleep_rows)

        if workout_rows:
            pd.DataFrame(workout_rows).to_parquet(
                out_dir / "workouts.parquet", index=False
            )
            stats.metrics_written["workouts"] = len(workout_rows)

        if activity_rows:
            pd.DataFrame(activity_rows).to_parquet(
                out_dir / "activity_rings.parquet", index=False
            )
            stats.metrics_written["activity_rings"] = len(activity_rows)

    finally:
        fileobj.close()
        if owning is not None:
            owning.close()

    return stats


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="Path to export.zip or export.xml")
    ap.add_argument(
        "--out",
        default="data/parquet",
        help="Output directory for parquet files",
    )
    args = ap.parse_args()

    stats = parse_export(args.source, args.out)
    print(f"Records:  {stats.record_count}")
    print(f"Sleep:    {stats.sleep_count}")
    print(f"Workouts: {stats.workout_count}")
    print("Per-metric rows written:")
    for k, v in sorted(stats.metrics_written.items()):
        print(f"  {k:30s} {v:>10,}")
