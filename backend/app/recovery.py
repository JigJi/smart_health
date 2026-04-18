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


def compute_sleep_quality(
    hours: float,
    deep_min: float | None,
    rem_min: float | None,
    awake_min: float | None,
    bedtime: str | None,
) -> int | None:
    """Quality-aware sleep score (0-100).

    Clinical literature (Walker, Oura, Whoop):
    - Deep sleep target: 60-90 min/night (13-23% of 7h)
    - REM target: 90-120 min/night (20-25% of 7h)
    - Sleep efficiency: time asleep / (asleep + awake)
    - Bedtime consistency: late bedtimes disrupt first deep sleep cycles

    Weights: Duration 35%, Deep 25%, REM 20%, Efficiency 10%, Bedtime 10%
    Falls back to duration-only if no stage data available.
    """
    total_min = hours * 60

    # Duration component (0-1): 7h target
    dur_score = max(0.0, min(1.0, total_min / 420))

    # If no stage data, return duration-only score (legacy nights)
    if deep_min is None and rem_min is None:
        return round(dur_score * 100)

    deep = deep_min or 0
    rem = rem_min or 0
    awake = awake_min or 0

    # Deep sleep component (0-1): target 60-90 min
    if deep >= 90:
        deep_score = 1.0
    elif deep >= 60:
        deep_score = 0.7 + 0.3 * (deep - 60) / 30
    elif deep >= 30:
        deep_score = 0.3 + 0.4 * (deep - 30) / 30
    else:
        deep_score = max(0.0, deep / 30 * 0.3)

    # REM component (0-1): target 90-120 min
    if rem >= 120:
        rem_score = 1.0
    elif rem >= 60:
        rem_score = 0.5 + 0.5 * (rem - 60) / 60
    else:
        rem_score = max(0.0, rem / 60 * 0.5)

    # Efficiency component (0-1): penalize time awake during sleep window
    if total_min + awake > 0:
        efficiency = total_min / (total_min + awake)
        eff_score = max(0.0, min(1.0, (efficiency - 0.75) / 0.20))  # 75%->0, 95%->1
    else:
        eff_score = 0.5

    # Bedtime component (0-1): earlier bedtime = better deep sleep quality
    bed_score = 1.0
    if bedtime:
        try:
            bh = int(bedtime.split(":")[0])
            if bh >= 21:
                bed_score = 1.0
            elif bh == 0:
                bed_score = 0.7
            elif bh == 1:
                bed_score = 0.35
            elif bh >= 2 and bh <= 5:
                bed_score = 0.1
        except (ValueError, IndexError):
            pass

    # Weighted combination
    score = (
        dur_score * 0.35 +
        deep_score * 0.25 +
        rem_score * 0.20 +
        eff_score * 0.10 +
        bed_score * 0.10
    )

    return round(score * 100)


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
    # Stage data for quality-aware scoring (modern nights only)
    sleep_detail_by_day = {
        r["day"]: r for r in sleep_rows
        if r.get("deep_min") is not None or r.get("rem_min") is not None
    }

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
            detail = sleep_detail_by_day.get(day)
            if detail:
                quality = compute_sleep_quality(
                    sleep_today / 60.0,
                    detail.get("deep_min"),
                    detail.get("rem_min"),
                    detail.get("awake_min"),
                    None,  # no bedtime in series context
                )
                sleep_score = (quality / 100.0) if quality is not None else min(1.0, sleep_today / SLEEP_TARGET_MIN)
            else:
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
