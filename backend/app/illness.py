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


# ─────────────────────────────────────────────────────────────────────
# Real-time illness watcher — focused on TODAY, for dashboard alerts.
# Complements detect_episodes() (historical) with a sharper Altini-style
# multi-signal rule: ≥2 signals = meaningful; sustained = high confidence.
# ─────────────────────────────────────────────────────────────────────

from pathlib import Path
from statistics import mean, pstdev

import duckdb


def _daily_series(parquet_dir: Path, file: str, days: int,
                  morning_only: bool = False) -> dict[date, float]:
    p = parquet_dir / file
    if not p.exists():
        return {}
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Bangkok'")
    where = f"CAST(start AS DATE) >= current_date - INTERVAL {days} DAY"
    if morning_only:
        where += " AND EXTRACT(hour FROM start) < 10"
    rows = con.execute(f"""
        SELECT CAST(start AS DATE) AS d, avg(value) AS v
        FROM read_parquet('{p.as_posix()}')
        WHERE {where}
        GROUP BY 1
    """).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def _day_zscore(val: float | None, series: dict[date, float], target: date) -> float | None:
    if val is None:
        return None
    base = [v for dd, v in series.items() if dd < target and (target - dd).days <= 60]
    if len(base) < 7:
        return None
    m = mean(base)
    s = pstdev(base) or 1.0
    return (val - m) / s


def _check_day_signals(parquet_dir: Path, d: date,
                       hrv: dict, rhr: dict, temp: dict) -> list[dict[str, Any]]:
    """Return list of signal dicts that fired on day `d`."""
    signals: list[dict[str, Any]] = []

    hrv_z = _day_zscore(hrv.get(d), hrv, d)
    if hrv_z is not None and hrv_z <= -1.5:
        signals.append({"metric": "HRV", "z": round(hrv_z, 1),
                        "msg": f"HRV ต่ำกว่าปกติ ({hrv_z:+.1f}σ)"})

    rhr_z = _day_zscore(rhr.get(d), rhr, d)
    if rhr_z is not None and rhr_z >= 1.5:
        signals.append({"metric": "RHR", "z": round(rhr_z, 1),
                        "msg": f"RHR สูงกว่าปกติ ({rhr_z:+.1f}σ)"})

    # Wrist temp — absolute °C delta vs baseline (not z-score; Apple's
    # post-iOS 16 temp is calibrated to show Δ directly)
    temp_val = temp.get(d)
    if temp_val is not None:
        temp_base = [v for dd, v in temp.items() if dd < d and (d - dd).days <= 60]
        if len(temp_base) >= 7:
            delta = temp_val - mean(temp_base)
            if delta >= 0.5:
                signals.append({"metric": "temp", "delta": round(delta, 2),
                                "msg": f"อุณหภูมิข้อมือสูง (+{delta:.1f}°C)"})
    return signals


def detect_today(parquet_dir: Path, target: date | None = None) -> dict[str, Any]:
    """Altini-style multi-signal illness watcher for dashboard.

    Confidence tiers:
      - high     : ≥2 signals AND yesterday also had ≥2 → sustained pattern
      - medium   : ≥2 signals today only → watchful
      - low      : 1 signal → could be coffee / bad sleep, not illness
      - None     : all normal
    """
    d = target or date.today()
    hrv  = _daily_series(parquet_dir, "hrv_sdnn.parquet", 90, morning_only=True)
    rhr  = _daily_series(parquet_dir, "resting_heart_rate.parquet", 90)
    temp = _daily_series(parquet_dir, "wrist_temperature.parquet", 90)

    today_signals = _check_day_signals(parquet_dir, d, hrv, rhr, temp)
    yest_signals  = _check_day_signals(parquet_dir, d - timedelta(days=1),
                                        hrv, rhr, temp)

    confidence: str | None = None
    if len(today_signals) >= 2 and len(yest_signals) >= 2:
        confidence = "high"
    elif len(today_signals) >= 2:
        confidence = "medium"
    elif len(today_signals) >= 1:
        confidence = "low"

    headline: str | None = None
    if confidence == "high":
        headline = "สัญญาณป่วยต่อเนื่อง 2 วัน ควรพักจริงจัง"
    elif confidence == "medium":
        headline = "มีสัญญาณผิดปกติหลายตัว วันนี้ — เฝ้าดูอีก 24 ชม."
    elif confidence == "low":
        headline = "มีสัญญาณเดียวผิดปกติ อาจเป็น noise ไม่แน่ใจ"

    return {
        "confidence": confidence,
        "headline": headline,
        "signals": today_signals,
        "sustained": len(yest_signals) >= 2,
    }
