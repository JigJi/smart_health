"""Daily status — plain-language per-day readiness.

Replaces raw z-score charts with a simple classification:
  normal  / warning  / bad  / no_data

Each day comes with Thai-language reason + recommendation so the
frontend can show the story, not just the numbers.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb


BASELINE_DAYS = 60

HRV_WARN = -1.0   # z-score
HRV_BAD = -1.8
RHR_WARN = 1.0
RHR_BAD = 1.8


def _baseline(values: list[float]) -> tuple[float, float] | None:
    if len(values) < 7:
        return None
    m = sum(values) / len(values)
    var = sum((x - m) ** 2 for x in values) / len(values)
    s = var ** 0.5 or 1.0
    return m, s


def daily_status(parquet_dir: str | Path, days: int = 35) -> dict[str, Any]:
    parquet_dir = Path(parquet_dir)
    con = duckdb.connect(":memory:")

    hrv_path = (parquet_dir / "hrv_sdnn.parquet").as_posix()
    rhr_path = (parquet_dir / "resting_heart_rate.parquet").as_posix()

    window = days + BASELINE_DAYS

    hrv_rows = con.execute(
        f"""
        SELECT CAST(start AS DATE) AS d, median(value) AS v
        FROM read_parquet('{hrv_path}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL {window} DAY
        GROUP BY 1
        ORDER BY 1
    """
    ).fetchall()
    rhr_rows = con.execute(
        f"""
        SELECT CAST(start AS DATE) AS d, avg(value) AS v
        FROM read_parquet('{rhr_path}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL {window} DAY
        GROUP BY 1
        ORDER BY 1
    """
    ).fetchall()

    hrv_by_day = {r[0]: float(r[1]) for r in hrv_rows}
    rhr_by_day = {r[0]: float(r[1]) for r in rhr_rows}

    # Also check if any HR samples exist per day — "was Watch worn?"
    hr_path = (parquet_dir / "heart_rate.parquet").as_posix()
    hr_rows = con.execute(
        f"""
        SELECT CAST(start AS DATE) AS d, count(*) AS n
        FROM read_parquet('{hr_path}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL {window} DAY
        GROUP BY 1
    """
    ).fetchall()
    hr_n_by_day = {r[0]: int(r[1]) for r in hr_rows}

    today = date.today()
    start_day = today - timedelta(days=days - 1)

    # Compute baselines once from the full prior window
    all_hrv = sorted(hrv_by_day.items())
    all_rhr = sorted(rhr_by_day.items())

    results: list[dict[str, Any]] = []
    for i in range(days):
        d = start_day + timedelta(days=i)

        hrv_today = hrv_by_day.get(d)
        rhr_today = rhr_by_day.get(d)
        hr_n = hr_n_by_day.get(d, 0)

        # Prior-only rolling baseline (no leakage)
        prior_hrv = [v for (dd, v) in all_hrv if dd < d and (d - dd).days <= BASELINE_DAYS]
        prior_rhr = [v for (dd, v) in all_rhr if dd < d and (d - dd).days <= BASELINE_DAYS]

        hrv_base = _baseline(prior_hrv)
        rhr_base = _baseline(prior_rhr)

        hrv_z: float | None = None
        rhr_z: float | None = None
        if hrv_today is not None and hrv_base:
            hrv_z = (hrv_today - hrv_base[0]) / hrv_base[1]
        if rhr_today is not None and rhr_base:
            # Invert: lower RHR is better, so positive z = worse
            rhr_z = (rhr_today - rhr_base[0]) / rhr_base[1]

        # Classify
        reasons_th: list[str] = []
        recommendation_th = ""

        has_any_signal = hrv_z is not None or rhr_z is not None
        watch_worn = hr_n >= 20  # some meaningful amount of data
        low_confidence = hr_n < 100  # less than ~1h of data → readings unreliable

        if not has_any_signal:
            if watch_worn:
                status = "no_signal"
                reasons_th.append("ไม่มี reading ของ HRV/RHR วันนี้")
                recommendation_th = "—"
            else:
                status = "no_data"
                reasons_th.append("ไม่ได้ใส่ Watch")
                recommendation_th = "—"
        elif low_confidence:
            # With very few samples, readings are unreliable — Apple needs
            # hours of sustained wear to produce trustworthy RHR/HRV.
            status = "low_confidence"
            reasons_th.append(
                f"ใส่ Watch สั้นเกินไป ({hr_n} samples) — ข้อมูลยังไม่น่าเชื่อถือ"
            )
            if hrv_today is not None:
                reasons_th.append(f"HRV {hrv_today:.0f} ms (อ้างอิงไม่ได้)")
            if rhr_today is not None:
                reasons_th.append(f"RHR {rhr_today:.0f} bpm (อ้างอิงไม่ได้)")
            recommendation_th = "ใส่ Watch นานขึ้นจะได้ข้อมูลที่แม่นยำ"
        else:
            hrv_bad = hrv_z is not None and hrv_z <= HRV_BAD
            hrv_warn = hrv_z is not None and hrv_z <= HRV_WARN
            rhr_bad = rhr_z is not None and rhr_z >= RHR_BAD
            rhr_warn = rhr_z is not None and rhr_z >= RHR_WARN

            if hrv_bad and rhr_bad:
                status = "bad"
                reasons_th.append(
                    f"HRV ต่ำมาก ({hrv_today:.0f} ms, baseline {hrv_base[0]:.0f})"
                )
                reasons_th.append(
                    f"RHR สูงมาก ({rhr_today:.0f} bpm, baseline {rhr_base[0]:.0f})"
                )
                recommendation_th = "ร่างกายฟ้องว่ามีอะไรผิดปกติ — ควรพัก งดออกกำลังกายหนัก"
            elif hrv_bad or rhr_bad:
                status = "bad"
                if hrv_bad:
                    reasons_th.append(
                        f"HRV ต่ำมาก {hrv_today:.0f} ms (ปกติ ~{hrv_base[0]:.0f})"
                    )
                if rhr_bad:
                    reasons_th.append(
                        f"RHR สูงมาก {rhr_today:.0f} bpm (ปกติ ~{rhr_base[0]:.0f})"
                    )
                recommendation_th = "ระบบประสาทเครียด — ควรเบาลง, พักผ่อนเพิ่ม"
            elif hrv_warn or rhr_warn:
                status = "warning"
                if hrv_warn:
                    reasons_th.append(
                        f"HRV ต่ำกว่าปกติ {hrv_today:.0f} ms (ปกติ ~{hrv_base[0]:.0f})"
                    )
                if rhr_warn:
                    reasons_th.append(
                        f"RHR สูงกว่าปกติ {rhr_today:.0f} bpm (ปกติ ~{rhr_base[0]:.0f})"
                    )
                recommendation_th = "ยังออกกำลังกายได้ แต่อย่า push หนัก"
            else:
                status = "normal"
                if hrv_today is not None:
                    reasons_th.append(
                        f"HRV {hrv_today:.0f} ms (ปกติ ~{hrv_base[0]:.0f})"
                    )
                if rhr_today is not None:
                    reasons_th.append(
                        f"RHR {rhr_today:.0f} bpm (ปกติ ~{rhr_base[0]:.0f})"
                    )
                recommendation_th = "ร่างกายพร้อม — เทรนได้ตามปกติ"

        results.append(
            {
                "day": str(d),
                "dow": d.strftime("%a"),
                "status": status,
                "hrv_ms": round(hrv_today, 1) if hrv_today is not None else None,
                "rhr_bpm": round(rhr_today, 1) if rhr_today is not None else None,
                "hrv_z": round(hrv_z, 2) if hrv_z is not None else None,
                "rhr_z": round(rhr_z, 2) if rhr_z is not None else None,
                "hrv_baseline": round(hrv_base[0], 1) if hrv_base else None,
                "rhr_baseline": round(rhr_base[0], 1) if rhr_base else None,
                "hr_samples": hr_n,
                "reasons_th": reasons_th,
                "recommendation_th": recommendation_th,
            }
        )

    today_entry = results[-1] if results else None

    # All-time HRV stats (for the "your normal" card)
    hrv_stats_row = con.execute(
        f"""
        SELECT
          round(median(value), 1),
          round(stddev_pop(value), 1),
          round(quantile(value, 0.25), 1),
          round(quantile(value, 0.75), 1),
          count(*)
        FROM read_parquet('{hrv_path}')
    """
    ).fetchone()
    rhr_stats_row = con.execute(
        f"""
        SELECT
          round(avg(value), 1),
          round(stddev_pop(value), 1),
          round(quantile(value, 0.25), 1),
          round(quantile(value, 0.75), 1),
          count(*)
        FROM read_parquet('{rhr_path}')
    """
    ).fetchone()

    return {
        "days": results,
        "today": today_entry,
        "personal_norms": {
            "hrv": {
                "median": hrv_stats_row[0],
                "std": hrv_stats_row[1],
                "p25": hrv_stats_row[2],
                "p75": hrv_stats_row[3],
                "samples": hrv_stats_row[4],
            },
            "rhr": {
                "mean": rhr_stats_row[0],
                "std": rhr_stats_row[1],
                "p25": rhr_stats_row[2],
                "p75": rhr_stats_row[3],
                "samples": rhr_stats_row[4],
            },
        },
    }
