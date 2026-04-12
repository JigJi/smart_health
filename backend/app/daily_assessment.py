"""Daily body-state assessment — your personal health narrator.

Classifies each day into a relatable state based on biometrics +
workout context. Not just "normal/bad" but richer categories that
feel like a coach/assistant telling you how your day went.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb


# Each state has: id, emoji, label_th, short description template
STATES = {
    "peak": {
        "emoji": "⚡",
        "label_th": "พร้อมสุด",
        "color": "#5be49b",
        "desc_th": "ร่างกายพร้อมเต็มที่ — HRV สูงกว่าปกติ, หัวใจเต้นช้าดี",
    },
    "energized": {
        "emoji": "😊",
        "label_th": "สดใส มีพลัง",
        "color": "#34d399",
        "desc_th": "ระบบประสาทสมดุลดี — วันนี้ push ได้ถ้าอยากออกกำลัง",
    },
    "normal": {
        "emoji": "👍",
        "label_th": "ปกติดี",
        "color": "#94a3b8",
        "desc_th": "ทุกอย่างอยู่ในเกณฑ์ปกติของคุณ",
    },
    "active_day": {
        "emoji": "💪",
        "label_th": "วันออกกำลัง",
        "color": "#60a5fa",
        "desc_th": "ออกกำลังกาย {workout_desc} — ร่างกาย handle ได้ดี",
    },
    "heavy_training": {
        "emoji": "🔥",
        "label_th": "ฝึกหนัก",
        "color": "#f97316",
        "desc_th": "workout หนักกว่าปกติ — พรุ่งนี้ควรพักหรือเบาลง",
    },
    "rest_day": {
        "emoji": "🛋️",
        "label_th": "วันพัก",
        "color": "#64748b",
        "desc_th": "ไม่ได้ออกกำลังกาย — ร่างกายได้ recover",
    },
    "stressed": {
        "emoji": "😤",
        "label_th": "เครียด",
        "color": "#f59e0b",
        "desc_th": "RHR สูงกว่าปกติโดยไม่ได้ออกกำลัง — อาจเครียดงาน/ชีวิต หรือนอนไม่พอ",
    },
    "tired": {
        "emoji": "😴",
        "label_th": "เหนื่อยสะสม",
        "color": "#a78bfa",
        "desc_th": "HRV ต่ำ + ออกกำลังมาติดต่อกัน — ร่างกายขอพัก",
    },
    "under_recovered": {
        "emoji": "😵",
        "label_th": "ฟื้นตัวไม่ทัน",
        "color": "#ef5350",
        "desc_th": "ทั้ง HRV ต่ำ + RHR สูง — ร่างกายยังไม่พร้อม ควรงดออกกำลังหนัก",
    },
    "unwell": {
        "emoji": "🤒",
        "label_th": "อาจไม่สบาย",
        "color": "#ef4444",
        "desc_th": "สัญญาณคล้ายป่วย — HRV crash + RHR พุ่ง ติดตามอาการอย่างใกล้ชิด",
    },
    "bounce_back": {
        "emoji": "🔄",
        "label_th": "กำลังฟื้นตัว",
        "color": "#22d3ee",
        "desc_th": "HRV กลับมาดีขึ้นหลังจากช่วงที่แย่ — ร่างกาย recover แล้ว",
    },
    "no_data": {
        "emoji": "⚪",
        "label_th": "ไม่ได้ใส่ Watch",
        "color": "#334155",
        "desc_th": "ไม่มีข้อมูลวันนี้",
    },
    "low_confidence": {
        "emoji": "❓",
        "label_th": "ข้อมูลไม่พอ",
        "color": "#475569",
        "desc_th": "ใส่ Watch สั้นเกินไป — ยังประเมินไม่ได้",
    },
}


def daily_assessment(parquet_dir: str | Path, days: int = 35) -> list[dict[str, Any]]:
    pq = Path(parquet_dir)
    con = duckdb.connect(":memory:")

    hrv_path = (pq / "hrv_sdnn.parquet").as_posix()
    rhr_path = (pq / "resting_heart_rate.parquet").as_posix()
    wk_path = (pq / "workouts.parquet").as_posix()
    hr_path = (pq / "heart_rate.parquet").as_posix()

    window = days + 60

    hrv_rows = con.execute(f"""
        SELECT CAST(start AS DATE) AS d, median(value) AS v
        FROM read_parquet('{hrv_path}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL {window} DAY
        GROUP BY 1 ORDER BY 1
    """).fetchall()

    rhr_rows = con.execute(f"""
        SELECT CAST(start AS DATE) AS d, avg(value) AS v
        FROM read_parquet('{rhr_path}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL {window} DAY
        GROUP BY 1 ORDER BY 1
    """).fetchall()

    wk_rows = con.execute(f"""
        SELECT CAST(start AS DATE) AS d,
               count(*) AS n,
               sum(duration_min) AS mins,
               max(hr_avg) AS peak_hr,
               REPLACE(
                 (SELECT type FROM read_parquet('{wk_path}') w2
                  WHERE CAST(w2.start AS DATE) = CAST(w.start AS DATE)
                  ORDER BY w2.duration_min DESC LIMIT 1),
                 'HKWorkoutActivityType', '') AS main_sport
        FROM read_parquet('{wk_path}') w
        WHERE CAST(start AS DATE) >= current_date - INTERVAL {window} DAY
        GROUP BY 1 ORDER BY 1
    """).fetchall()

    hr_counts = con.execute(f"""
        SELECT CAST(start AS DATE) AS d, count(*) AS n
        FROM read_parquet('{hr_path}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL {window} DAY
        GROUP BY 1
    """).fetchall()

    hrv_by_day = {r[0]: float(r[1]) for r in hrv_rows}
    rhr_by_day = {r[0]: float(r[1]) for r in rhr_rows}
    wk_by_day = {r[0]: {"n": r[1], "mins": r[2], "peak_hr": r[3], "sport": r[4]} for r in wk_rows}
    hr_n_by_day = {r[0]: int(r[1]) for r in hr_counts}

    all_hrv = sorted(hrv_by_day.items())
    all_rhr = sorted(rhr_by_day.items())

    today = date.today()
    start_day = today - timedelta(days=days - 1)

    results: list[dict[str, Any]] = []

    for i in range(days):
        d = start_day + timedelta(days=i)

        hrv = hrv_by_day.get(d)
        rhr = rhr_by_day.get(d)
        wk = wk_by_day.get(d)
        hr_n = hr_n_by_day.get(d, 0)

        # Baselines
        prior_hrv = [v for (dd, v) in all_hrv if dd < d and (d - dd).days <= 60]
        prior_rhr = [v for (dd, v) in all_rhr if dd < d and (d - dd).days <= 60]

        hrv_z = None
        rhr_z = None
        if hrv is not None and len(prior_hrv) >= 7:
            m = sum(prior_hrv) / len(prior_hrv)
            s = (sum((x - m) ** 2 for x in prior_hrv) / len(prior_hrv)) ** 0.5 or 1
            hrv_z = (hrv - m) / s
        if rhr is not None and len(prior_rhr) >= 7:
            m = sum(prior_rhr) / len(prior_rhr)
            s = (sum((x - m) ** 2 for x in prior_rhr) / len(prior_rhr)) ** 0.5 or 1
            rhr_z = (rhr - m) / s

        # Previous days context
        prev_wk = wk_by_day.get(d - timedelta(days=1))
        prev2_wk = wk_by_day.get(d - timedelta(days=2))
        consec_workout = bool(wk and prev_wk)
        prev_hrv_z = None
        prev_d = d - timedelta(days=1)
        prev_hrv = hrv_by_day.get(prev_d)
        if prev_hrv is not None and len(prior_hrv) >= 7:
            m = sum(prior_hrv) / len(prior_hrv)
            s = (sum((x - m) ** 2 for x in prior_hrv) / len(prior_hrv)) ** 0.5 or 1
            prev_hrv_z = (prev_hrv - m) / s

        # Classify
        state = _classify(
            hrv_z=hrv_z,
            rhr_z=rhr_z,
            has_workout=wk is not None,
            workout_heavy=wk is not None and wk["peak_hr"] is not None and hrv_z is not None and wk["peak_hr"] > 160,
            consec_workout=consec_workout,
            hr_n=hr_n,
            prev_hrv_z=prev_hrv_z,
        )

        meta = STATES[state]
        desc = meta["desc_th"]
        if state == "active_day" and wk:
            sport = wk["sport"] or "workout"
            desc = desc.replace("{workout_desc}", f"{sport} {wk['mins']:.0f} นาที")

        # Build metrics line
        metrics: list[str] = []
        if hrv is not None:
            metrics.append(f"HRV {hrv:.0f} ms")
        if rhr is not None:
            metrics.append(f"RHR {rhr:.0f} bpm")
        if wk:
            metrics.append(f"{wk['n']} workout{'s' if wk['n'] > 1 else ''}")

        results.append({
            "day": str(d),
            "dow": d.strftime("%a"),
            "state": state,
            "emoji": meta["emoji"],
            "label_th": meta["label_th"],
            "color": meta["color"],
            "desc_th": desc,
            "metrics": " · ".join(metrics) if metrics else "ไม่มีข้อมูล",
            "hrv_ms": round(hrv, 1) if hrv is not None else None,
            "rhr_bpm": round(rhr, 1) if rhr is not None else None,
            "hrv_z": round(hrv_z, 2) if hrv_z is not None else None,
            "rhr_z": round(rhr_z, 2) if rhr_z is not None else None,
        })

    return results


def _classify(
    *,
    hrv_z: float | None,
    rhr_z: float | None,
    has_workout: bool,
    workout_heavy: bool,
    consec_workout: bool,
    hr_n: int,
    prev_hrv_z: float | None,
) -> str:
    # No data
    if hr_n == 0:
        return "no_data"
    if hr_n < 100:
        return "low_confidence"

    has_hrv = hrv_z is not None
    has_rhr = rhr_z is not None

    if not has_hrv and not has_rhr:
        if has_workout:
            return "active_day"
        return "rest_day"

    # Illness-like: both very bad
    if has_hrv and has_rhr and hrv_z <= -1.8 and rhr_z >= 1.8:
        return "unwell"

    # Under-recovered: both bad
    if has_hrv and has_rhr and hrv_z <= -1.0 and rhr_z >= 1.0:
        return "under_recovered"

    # Bounce back: was bad yesterday, better today
    if has_hrv and prev_hrv_z is not None and prev_hrv_z <= -1.0 and hrv_z > -0.3:
        return "bounce_back"

    # Stressed: RHR high but no heavy workout to explain it
    if has_rhr and rhr_z >= 1.2 and not has_workout:
        return "stressed"

    # Tired/fatigued: HRV low after consecutive workouts
    if has_hrv and hrv_z <= -0.8 and consec_workout:
        return "tired"

    # Heavy training day
    if workout_heavy:
        return "heavy_training"

    # Active day with workout
    if has_workout:
        return "active_day"

    # Peak readiness
    if has_hrv and hrv_z >= 1.0 and (not has_rhr or rhr_z <= 0):
        return "peak"

    # Energized: HRV above average
    if has_hrv and hrv_z >= 0.3:
        return "energized"

    # Rest day without workout
    if not has_workout:
        return "rest_day"

    return "normal"
