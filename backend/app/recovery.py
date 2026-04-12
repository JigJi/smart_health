"""Whoop-style recovery score (0-100).

The real Whoop formula is proprietary, but the public literature is clear
on the ingredients:

  1. HRV today vs personal rolling baseline (weighted most)
  2. Resting HR today vs personal rolling baseline
  3. Sleep performance (actual / need) — we use 7h as a simple target

Each component is normalized to 0-1 and combined. Because HRV is highly
individual, comparing to YOUR OWN baseline (not population norms) is the
whole point — this is why you need 2+ weeks of data before the score
becomes meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from statistics import mean, pstdev
from typing import Any

from .queries import HealthStore


# Component weights — HRV carries the most signal, per Whoop whitepaper.
W_HRV = 0.55
W_RHR = 0.25
W_SLEEP = 0.20

BASELINE_DAYS = 30
SLEEP_TARGET_MIN = 7 * 60  # 7 hours


@dataclass
class RecoveryComponents:
    hrv_score: float | None      # 0..1
    rhr_score: float | None      # 0..1 (lower RHR is better)
    sleep_score: float | None    # 0..1
    recovery: float | None       # 0..100
    # diagnostics for UI tooltips
    hrv_today: float | None = None
    hrv_baseline: float | None = None
    rhr_today: float | None = None
    rhr_baseline: float | None = None
    sleep_today_min: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _zscore_to_unit(z: float, cap: float = 2.0) -> float:
    """Map a z-score to 0..1 with soft saturation at +/- `cap` sigma."""
    clipped = max(-cap, min(cap, z))
    return (clipped + cap) / (2 * cap)


def _baseline(series: list[float]) -> tuple[float, float] | None:
    """Return (mean, stddev) from a list, or None if too few points."""
    if len(series) < 7:
        return None
    m = mean(series)
    s = pstdev(series) or 1.0  # avoid div-by-zero for flat series
    return m, s


def compute_recovery_series(store: HealthStore, days: int = 60) -> list[dict[str, Any]]:
    """Compute a recovery score for each day in the range.

    Uses an EXPANDING baseline: for each target day we only look back at
    prior days, never leaking future data into 'today's' comparison.
    """
    hrv_rows = store.daily_hrv(days + BASELINE_DAYS)
    rhr_rows = store.daily_resting_hr(days + BASELINE_DAYS)
    sleep_rows = store.daily_sleep(days + BASELINE_DAYS)

    hrv_by_day = {r["day"]: r["hrv_ms"] for r in hrv_rows if r["hrv_ms"] is not None}
    rhr_by_day = {r["day"]: r["rhr_bpm"] for r in rhr_rows if r["rhr_bpm"] is not None}
    sleep_by_day = {r["day"]: r["asleep_min"] for r in sleep_rows}

    all_days = sorted(set(hrv_by_day) | set(rhr_by_day) | set(sleep_by_day))
    out: list[dict[str, Any]] = []

    for day in all_days:
        prior_hrv = [
            hrv_by_day[d]
            for d in hrv_by_day
            if d < day and (day - d).days <= BASELINE_DAYS
        ]
        prior_rhr = [
            rhr_by_day[d]
            for d in rhr_by_day
            if d < day and (day - d).days <= BASELINE_DAYS
        ]

        hrv_today = hrv_by_day.get(day)
        rhr_today = rhr_by_day.get(day)
        sleep_today = sleep_by_day.get(day)

        hrv_score: float | None = None
        rhr_score: float | None = None
        sleep_score: float | None = None
        hrv_baseline_mean: float | None = None
        rhr_baseline_mean: float | None = None

        if hrv_today is not None:
            base = _baseline(prior_hrv)
            if base:
                hrv_baseline_mean = base[0]
                z = (hrv_today - base[0]) / base[1]
                hrv_score = _zscore_to_unit(z)

        if rhr_today is not None:
            base = _baseline(prior_rhr)
            if base:
                rhr_baseline_mean = base[0]
                # Lower RHR is better → invert sign.
                z = (base[0] - rhr_today) / base[1]
                rhr_score = _zscore_to_unit(z)

        if sleep_today is not None:
            sleep_score = min(1.0, sleep_today / SLEEP_TARGET_MIN)

        # Combine only the components we actually have — re-normalize weights.
        parts: list[tuple[float, float]] = []
        if hrv_score is not None:
            parts.append((hrv_score, W_HRV))
        if rhr_score is not None:
            parts.append((rhr_score, W_RHR))
        if sleep_score is not None:
            parts.append((sleep_score, W_SLEEP))

        recovery: float | None = None
        if parts:
            total_w = sum(w for _, w in parts)
            recovery = round(100 * sum(s * w for s, w in parts) / total_w, 1)

        out.append(
            {
                "day": str(day),
                "recovery": recovery,
                "hrv_score": hrv_score,
                "rhr_score": rhr_score,
                "sleep_score": sleep_score,
                "hrv_today": hrv_today,
                "hrv_baseline": hrv_baseline_mean,
                "rhr_today": rhr_today,
                "rhr_baseline": rhr_baseline_mean,
                "sleep_today_min": sleep_today,
            }
        )

    # Only return the last `days` days so frontend doesn't see the warmup.
    return out[-days:]
