"""Illness / physiological anomaly detector.

Whoop-style: your body's autonomic nervous system reacts to infection,
hangover, poor sleep, major stress, jet lag — all before you 'feel' it.
The signature is:

    RHR ↑  (sympathetic drive kicks in)
    HRV ↓  (parasympathetic suppressed)
    Activity ↓ (you naturally move less)

We z-score each signal against a 60-day personal rolling baseline and
flag days where at least RHR or HRV crosses a threshold. Consecutive
flagged days are collapsed into 'episodes.'
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta
from typing import Any

from .queries import HealthStore


BASELINE_DAYS = 60
# Thresholds tuned to catch real episodes without flooding false positives.
RHR_THRESHOLD = 1.2     # z-score (≈ +1.2σ above personal normal)
HRV_THRESHOLD = -1.2    # z-score (≈ -1.2σ below personal normal)
MIN_SIGNAL_DAYS = 7     # need this many prior days for a valid baseline


@dataclass
class Episode:
    start: str
    end: str
    days: int
    peak_rhr_z: float | None
    trough_hrv_z: float | None
    peak_rhr_bpm: float | None
    trough_hrv_ms: float | None
    severity: str   # mild / moderate / severe


def _rolling_baseline(values: list[tuple[date, float]], target: date) -> tuple[float, float] | None:
    window = [
        v for d, v in values
        if (target - d).days > 0 and (target - d).days <= BASELINE_DAYS
    ]
    if len(window) < MIN_SIGNAL_DAYS:
        return None
    m = sum(window) / len(window)
    var = sum((x - m) ** 2 for x in window) / len(window)
    s = var ** 0.5 or 1.0
    return m, s


def detect_episodes(store: HealthStore, days: int = 365 * 6) -> dict[str, Any]:
    """Return daily anomaly flags + grouped episodes for the last `days`."""
    rhr_rows = store.daily_resting_hr(days)
    hrv_rows = store.daily_hrv(days)

    rhr_series: list[tuple[date, float]] = [
        (r["day"], float(r["rhr_bpm"])) for r in rhr_rows if r["rhr_bpm"] is not None
    ]
    hrv_series: list[tuple[date, float]] = [
        (r["day"], float(r["hrv_ms"])) for r in hrv_rows if r["hrv_ms"] is not None
    ]

    rhr_by_day = dict(rhr_series)
    hrv_by_day = dict(hrv_series)
    all_days = sorted(set(rhr_by_day) | set(hrv_by_day))

    flags: list[dict[str, Any]] = []
    for d in all_days:
        rhr_z: float | None = None
        hrv_z: float | None = None

        if d in rhr_by_day:
            base = _rolling_baseline(rhr_series, d)
            if base:
                rhr_z = (rhr_by_day[d] - base[0]) / base[1]

        if d in hrv_by_day:
            base = _rolling_baseline(hrv_series, d)
            if base:
                hrv_z = (hrv_by_day[d] - base[0]) / base[1]

        flagged = (
            (rhr_z is not None and rhr_z >= RHR_THRESHOLD)
            or (hrv_z is not None and hrv_z <= HRV_THRESHOLD)
        )
        both = (
            rhr_z is not None
            and hrv_z is not None
            and rhr_z >= RHR_THRESHOLD
            and hrv_z <= HRV_THRESHOLD
        )
        flags.append(
            {
                "day": str(d),
                "rhr_bpm": rhr_by_day.get(d),
                "hrv_ms": hrv_by_day.get(d),
                "rhr_z": round(rhr_z, 2) if rhr_z is not None else None,
                "hrv_z": round(hrv_z, 2) if hrv_z is not None else None,
                "flagged": flagged,
                "both_signals": both,
            }
        )

    # Collapse consecutive flagged days (allow 1-day gap) into episodes.
    episodes: list[Episode] = []
    cur: list[dict[str, Any]] = []

    def _close() -> None:
        if not cur:
            return
        peak_rhr_z = max(
            (f["rhr_z"] for f in cur if f["rhr_z"] is not None), default=None
        )
        trough_hrv_z = min(
            (f["hrv_z"] for f in cur if f["hrv_z"] is not None), default=None
        )
        peak_rhr = max(
            (f["rhr_bpm"] for f in cur if f["rhr_bpm"] is not None), default=None
        )
        trough_hrv = min(
            (f["hrv_ms"] for f in cur if f["hrv_ms"] is not None), default=None
        )

        # Severity: severe = both signals + multi-day OR extreme z-scores
        strong_rhr = peak_rhr_z is not None and peak_rhr_z >= 2.0
        strong_hrv = trough_hrv_z is not None and trough_hrv_z <= -2.0
        any_both = any(f["both_signals"] for f in cur)

        if (strong_rhr and strong_hrv) or (any_both and len(cur) >= 3):
            sev = "severe"
        elif any_both or strong_rhr or strong_hrv:
            sev = "moderate"
        else:
            sev = "mild"

        episodes.append(
            Episode(
                start=cur[0]["day"],
                end=cur[-1]["day"],
                days=len(cur),
                peak_rhr_z=peak_rhr_z,
                trough_hrv_z=trough_hrv_z,
                peak_rhr_bpm=peak_rhr,
                trough_hrv_ms=trough_hrv,
                severity=sev,
            )
        )

    last_day: date | None = None
    for f in flags:
        if not f["flagged"]:
            # Allow single-day gaps inside an episode.
            if cur and last_day is not None:
                gap = (date.fromisoformat(f["day"][:10]) - last_day).days
                if gap <= 2:
                    continue
            _close()
            cur = []
            last_day = None
            continue
        cur.append(f)
        last_day = date.fromisoformat(f["day"][:10])
    _close()

    return {
        "episode_count": len(episodes),
        "episodes": [asdict(e) for e in episodes],
        "flags": flags,
    }
