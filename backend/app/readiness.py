"""Readiness score + unified /today endpoint.

Combines recovery, daily_status, strain, sleep, and workout data
into a single payload for the dashboard. Includes Thai-language
tips based on personal patterns discovered from 5 years of data.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from .queries import HealthStore
from .recovery import compute_recovery_series


def _query(parquet_dir: Path, sql: str) -> list:
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Bangkok'")
    return con.execute(sql).fetchall()


def _get_today_hrv(parquet_dir: Path) -> tuple[float | None, float | None]:
    """Return (today_hrv, baseline_hrv)."""
    p = parquet_dir / "hrv_sdnn.parquet"
    if not p.exists():
        return None, None
    rows = _query(parquet_dir, f"""
        SELECT CAST(start AS DATE) AS d, median(value) AS v
        FROM read_parquet('{p.as_posix()}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL 90 DAY
        GROUP BY 1 ORDER BY 1
    """)
    if not rows:
        return None, None
    by_day = {r[0]: float(r[1]) for r in rows}
    today = date.today()
    today_val = by_day.get(today)
    prior = [v for d, v in by_day.items() if d < today and (today - d).days <= 60]
    baseline = sum(prior) / len(prior) if len(prior) >= 7 else None
    return today_val, baseline


def _get_today_rhr(parquet_dir: Path) -> tuple[float | None, float | None]:
    """Return (today_rhr, baseline_rhr)."""
    p = parquet_dir / "resting_heart_rate.parquet"
    if not p.exists():
        return None, None
    rows = _query(parquet_dir, f"""
        SELECT CAST(start AS DATE) AS d, avg(value) AS v
        FROM read_parquet('{p.as_posix()}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL 90 DAY
        GROUP BY 1 ORDER BY 1
    """)
    if not rows:
        return None, None
    by_day = {r[0]: float(r[1]) for r in rows}
    today = date.today()
    today_val = by_day.get(today)
    prior = [v for d, v in by_day.items() if d < today and (today - d).days <= 60]
    baseline = sum(prior) / len(prior) if len(prior) >= 7 else None
    return today_val, baseline


def _get_prev_steps(parquet_dir: Path) -> float | None:
    """Steps from yesterday."""
    p = parquet_dir / "steps.parquet"
    if not p.exists():
        return None
    rows = _query(parquet_dir, f"""
        SELECT sum(value) AS s
        FROM read_parquet('{p.as_posix()}')
        WHERE CAST(start AS DATE) = current_date - INTERVAL 1 DAY
    """)
    return float(rows[0][0]) if rows and rows[0][0] else None


def _get_today_strain(parquet_dir: Path) -> dict[str, Any]:
    """Today's strain: active kcal + steps + workouts."""
    result: dict[str, Any] = {"active_kcal": 0, "steps": 0, "workouts": []}

    # Active calories
    p = parquet_dir / "active_energy_kcal.parquet"
    if p.exists():
        rows = _query(parquet_dir, f"""
            SELECT sum(value) FROM read_parquet('{p.as_posix()}')
            WHERE CAST(start AS DATE) = current_date
        """)
        if rows and rows[0][0]:
            result["active_kcal"] = round(float(rows[0][0]))

    # Steps
    p = parquet_dir / "steps.parquet"
    if p.exists():
        rows = _query(parquet_dir, f"""
            SELECT sum(value) FROM read_parquet('{p.as_posix()}')
            WHERE CAST(start AS DATE) = current_date
        """)
        if rows and rows[0][0]:
            result["steps"] = round(float(rows[0][0]))

    # Workouts today
    p = parquet_dir / "workouts.parquet"
    if p.exists():
        rows = _query(parquet_dir, f"""
            SELECT type, duration_min, active_kcal, start
            FROM read_parquet('{p.as_posix()}')
            WHERE CAST(start AS DATE) = current_date
            ORDER BY start DESC
        """)
        for r in rows:
            wtype = r[0].replace("HKWorkoutActivityType", "") if r[0] else "Other"
            start_time = r[3].strftime("%H:%M") if r[3] else None
            result["workouts"].append({
                "type": wtype,
                "duration_min": round(float(r[1])) if r[1] else 0,
                "kcal": round(float(r[2])) if r[2] else 0,
                "time": start_time,
            })

    # Strain score (0-100) based on active kcal vs personal average
    p_energy = parquet_dir / "active_energy_kcal.parquet"
    if p_energy.exists():
        rows = _query(parquet_dir, f"""
            SELECT avg(daily_kcal) FROM (
                SELECT CAST(start AS DATE) AS d, sum(value) AS daily_kcal
                FROM read_parquet('{p_energy.as_posix()}')
                WHERE CAST(start AS DATE) >= current_date - INTERVAL 30 DAY
                  AND CAST(start AS DATE) < current_date
                GROUP BY 1
            )
        """)
        avg_kcal = float(rows[0][0]) if rows and rows[0][0] else 500
        # Scale: avg day = ~30%, max day (2x avg) = ~60%, rest day = ~5%
        result["score"] = min(100, round(result["active_kcal"] / avg_kcal * 30))
    else:
        result["score"] = 0

    # Thai label
    score = result["score"]
    if score >= 70:
        result["label"] = "หนักมาก"
    elif score >= 50:
        result["label"] = "หนัก"
    elif score >= 30:
        result["label"] = "ปานกลาง"
    elif score >= 10:
        result["label"] = "เบา"
    else:
        result["label"] = "พัก"

    return result


def _get_sleep(parquet_dir: Path) -> dict[str, Any]:
    """Last night's sleep summary."""
    p = parquet_dir / "sleep.parquet"
    if not p.exists():
        return {"hours": None, "quality_label": "ไม่มีข้อมูล"}

    # Look at sleep that ended today (last night's sleep)
    # Filter to only sleep sessions between 8pm yesterday and 2pm today
    rows = _query(parquet_dir, f"""
        SELECT
            min(start) AS bedtime,
            max("end") AS wakeup,
            SUM(CASE WHEN (stage LIKE '%AsleepCore%' OR stage LIKE '%AsleepDeep%'
                          OR stage LIKE '%AsleepREM%') THEN
                EXTRACT(EPOCH FROM ("end" - start)) / 3600.0 ELSE 0 END) AS hours
        FROM read_parquet('{p.as_posix()}')
        WHERE CAST("end" AS DATE) = current_date
          AND start >= current_date - INTERVAL 1 DAY + INTERVAL 20 HOUR
          AND "end" <= current_date + INTERVAL 14 HOUR
    """)

    if not rows or rows[0][2] is None or float(rows[0][2]) == 0:
        return {"hours": None, "quality_label": "ไม่มีข้อมูล"}

    hours = round(float(rows[0][2]), 1)
    bedtime = rows[0][0]
    wakeup = rows[0][1]

    if hours >= 7.5:
        label = "ดีมาก"
    elif hours >= 6.5:
        label = "พอดี"
    elif hours >= 5.5:
        label = "น้อยไป"
    else:
        label = "น้อยมาก"

    return {
        "hours": hours,
        "quality_label": label,
        "bedtime": str(bedtime.strftime("%H:%M")) if bedtime else None,
        "wakeup": str(wakeup.strftime("%H:%M")) if wakeup else None,
    }


def _get_gym_streak(parquet_dir: Path) -> int:
    """Count consecutive gym days before today."""
    p = parquet_dir / "workouts.parquet"
    if not p.exists():
        return 0
    gym_types = (
        "'HKWorkoutActivityTypeTraditionalStrengthTraining',"
        "'HKWorkoutActivityTypeFunctionalStrengthTraining',"
        "'HKWorkoutActivityTypeElliptical',"
        "'HKWorkoutActivityTypeCycling',"
        "'HKWorkoutActivityTypeBoxing',"
        "'HKWorkoutActivityTypeCoreTraining',"
        "'HKWorkoutActivityTypeHighIntensityIntervalTraining',"
        "'HKWorkoutActivityTypeCardioDance'"
    )
    rows = _query(parquet_dir, f"""
        SELECT DISTINCT CAST(start AS DATE) AS d
        FROM read_parquet('{p.as_posix()}')
        WHERE type IN ({gym_types})
          AND CAST(start AS DATE) >= current_date - INTERVAL 14 DAY
          AND CAST(start AS DATE) < current_date
        ORDER BY d DESC
    """)
    if not rows:
        return 0

    streak = 0
    today = date.today()
    for i in range(1, 15):
        check = today - timedelta(days=i)
        if any(r[0] == check for r in rows):
            streak += 1
        else:
            break
    return streak


def _signal_status(value: float | None, baseline: float | None, metric: str) -> str:
    """Classify a signal as good/normal/warning/bad."""
    if value is None or baseline is None:
        return "no_data"
    if metric == "hrv":
        diff_pct = (value - baseline) / baseline
        if diff_pct > 0.1:
            return "good"
        elif diff_pct > -0.1:
            return "normal"
        elif diff_pct > -0.25:
            return "warning"
        else:
            return "bad"
    elif metric == "rhr":
        diff = value - baseline
        if diff < -2:
            return "good"
        elif diff < 2:
            return "normal"
        elif diff < 5:
            return "warning"
        else:
            return "bad"
    return "normal"


def compute_readiness(
    hrv: float | None, hrv_base: float | None,
    rhr: float | None, rhr_base: float | None,
    prev_steps: float | None,
    streak: int,
    sleep_hours: float | None,
    dow: int,  # 0=Mon
) -> tuple[int, str, str, str]:
    """Return (score 0-100, label, color, reason)."""
    score = 50
    reasons = []

    # HRV signal — cap bonus to avoid over-optimism from spikes
    if hrv is not None and hrv_base is not None:
        diff_pct = (hrv - hrv_base) / hrv_base
        if diff_pct > 0.15:
            score += 8
        elif diff_pct > 0.05:
            score += 5
        elif diff_pct < -0.25:
            score -= 20
            reasons.append(f"HRV ต่ำมาก ({hrv:.0f} vs ปกติ {hrv_base:.0f})")
        elif diff_pct < -0.1:
            score -= 10
            reasons.append(f"HRV ต่ำกว่าปกติ ({hrv:.0f} ms)")

    # RHR signal
    if rhr is not None and rhr_base is not None:
        diff = rhr - rhr_base
        if diff < -3:
            score += 10
        elif diff > 6:
            score -= 15
            reasons.append(f"RHR สูงมาก ({rhr:.0f} vs ปกติ {rhr_base:.0f})")
        elif diff > 3:
            score -= 8
            reasons.append(f"RHR สูงกว่าปกติ ({rhr:.0f} bpm)")

    # Previous day steps
    if prev_steps is not None:
        if prev_steps < 5000:
            score += 10
            # ไม่ต้องบอก — เป็นสิ่งดี ไม่ต้องอธิบาย
        elif prev_steps > 15000:
            score -= 15
            reasons.append(f"เมื่อวานเดินเยอะ ({prev_steps:,.0f} ก้าว)")
        elif prev_steps > 12000:
            score -= 8
            reasons.append(f"เมื่อวานเดินค่อนข้างเยอะ ({prev_steps:,.0f} ก้าว)")

    # Streak fatigue
    if streak >= 4:
        score -= 15
        reasons.append(f"ยิมติดกัน {streak} วัน ควรพัก!")
    elif streak >= 3:
        score -= 8
        reasons.append(f"ยิมติดกัน {streak} วัน")

    # Sleep
    if sleep_hours is not None:
        if sleep_hours < 5:
            score -= 15
            reasons.append(f"นอนน้อยมาก ({sleep_hours:.1f} ชม.)")
        elif sleep_hours < 6:
            score -= 8
            reasons.append(f"นอนน้อย ({sleep_hours:.1f} ชม.)")
        elif sleep_hours >= 8:
            score += 5

    # Friday penalty
    if dow == 4:
        score -= 5

    # Late bedtime penalty (after midnight = bad quality sleep)
    # This is passed separately
    score = max(0, min(100, score))

    # Label + color
    if score >= 70:
        label = "พร้อมเต็มที่"
        color = "green"
    elif score >= 50:
        label = "พร้อม"
        color = "green"
    elif score >= 35:
        label = "ระวังหน่อย"
        color = "yellow"
    else:
        label = "ควรพัก"
        color = "red"

    reason = " · ".join(reasons) if reasons else "ร่างกายปกติดี"

    return score, label, color, reason


def _generate_tip(
    score: int, streak: int, prev_steps: float | None,
    sleep_hours: float | None, dow: int,
    already_worked_out: bool = False,
) -> str:
    """Generate a Thai tip based on signals."""
    if already_worked_out:
        if sleep_hours and sleep_hours < 6:
            return "คืนนี้นอนเร็วกว่าเมื่อคืนนะ"
        if score < 35:
            return "วันนี้พอแล้ว พักผ่อนให้เต็มที่"
        return ""

    if score < 35:
        if sleep_hours and sleep_hours < 6:
            return "วันนี้พักไปเลย ร่างกายต้องการเวลาฟื้นตัว"
        return "วันนี้ควรพัก"

    if streak >= 3:
        return "ยิมมาหลายวันติด พรุ่งนี้ควรพัก"

    if prev_steps and prev_steps > 15000:
        return "เมื่อวานเดินเยอะ ถ้าไปยิมวันนี้เน้น upper body"

    if sleep_hours and sleep_hours < 6:
        return "นอนน้อย ถ้าไปยิมให้สั้นลง"

    if dow == 4:
        return "วันศุกร์ สะสมมาทั้งสัปดาห์ ถ้าไม่ไหวพักได้"

    if score >= 70:
        return "วันนี้พร้อม ลุยได้เลย"

    return ""


def _get_weather() -> dict[str, Any]:
    """Fetch current weather + air quality for Bangkok."""
    import urllib.request
    import ssl
    import json as _json

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    result: dict[str, Any] = {}

    # Weather
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=13.76&longitude=100.50&current=temperature_2m,weather_code&timezone=Asia/Bangkok"
        with urllib.request.urlopen(url, timeout=5, context=ctx) as resp:
            data = _json.loads(resp.read())
            current = data.get("current", {})
            result["temp"] = round(current.get("temperature_2m", 0))

            # Weather code to Thai
            code = current.get("weather_code", 0)
            if code == 0:
                result["weather"] = "ท้องฟ้าแจ่มใส"
            elif code <= 3:
                result["weather"] = "มีเมฆบ้าง"
            elif code <= 48:
                result["weather"] = "มีหมอก"
            elif code <= 67:
                result["weather"] = "ฝนตก"
            elif code <= 77:
                result["weather"] = "หิมะ"
            elif code <= 82:
                result["weather"] = "ฝนตกหนัก"
            elif code <= 86:
                result["weather"] = "หิมะหนัก"
            elif code <= 99:
                result["weather"] = "พายุฝนฟ้าคะนอง"
            else:
                result["weather"] = "—"
    except Exception:
        result["temp"] = None
        result["weather"] = "—"

    # Air quality (PM2.5)
    try:
        url = "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=13.76&longitude=100.50&current=pm2_5&timezone=Asia/Bangkok"
        with urllib.request.urlopen(url, timeout=5, context=ctx) as resp:
            data = _json.loads(resp.read())
            pm = data.get("current", {}).get("pm2_5")
            result["pm25"] = round(pm) if pm else None
            if pm:
                if pm <= 25:
                    result["pm25_label"] = "ดี"
                elif pm <= 50:
                    result["pm25_label"] = "ปานกลาง"
                elif pm <= 100:
                    result["pm25_label"] = "ไม่ดี"
                else:
                    result["pm25_label"] = "อันตราย"
            else:
                result["pm25_label"] = "—"
    except Exception:
        result["pm25"] = None
        result["pm25_label"] = "—"

    return result


def _build_natural_reason(data: dict[str, Any]) -> str:
    """Build a natural Thai sentence from signals — deterministic, no LLM."""
    signals = data["signals"]
    parts = []

    # Sleep
    sleep_h = signals["sleep"].get("hours")
    bedtime = signals["sleep"].get("bedtime")
    if sleep_h is not None and bedtime:
        hour = int(bedtime.split(":")[0])
        if sleep_h < 5:
            parts.append(f"เมื่อคืนนอนตี {hour} นอนจริงแค่ {sleep_h:.0f} ชั่วโมง")
        elif sleep_h < 6:
            parts.append(f"เมื่อคืนนอน {sleep_h:.0f} ชั่วโมง น้อยไปหน่อย")
        elif hour >= 1 and hour <= 4:
            parts.append(f"เมื่อคืนนอนดึก แต่นอนได้ {sleep_h:.0f} ชั่วโมง")

    # Workouts done today
    workouts = data["strain"].get("workouts", [])
    if workouts:
        names = []
        for w in workouts:
            t = w["type"]
            if "Strength" in t:
                names.append("เวท")
            elif t == "Walking":
                names.append("เดิน")
            elif t == "Cycling":
                names.append("ปั่นจักรยาน")
            elif t == "Boxing":
                names.append("มวย")
            else:
                names.append(t)
        parts.append(f"วันนี้ออกกำลังกายไปแล้ว {'กับ'.join(names)}")

    # HRV/RHR anomalies — only mention if bad
    hrv = signals["hrv"]
    rhr = signals["rhr"]
    if hrv.get("status") == "bad":
        parts.append(f"HRV ต่ำมาก ร่างกายยังไม่ฟื้น")
    elif hrv.get("status") == "warning":
        parts.append("HRV ต่ำกว่าปกติ")

    if rhr.get("status") == "bad":
        parts.append("หัวใจเต้นเร็วกว่าปกติมาก")
    elif rhr.get("status") == "warning":
        parts.append("หัวใจเต้นเร็วกว่าปกติเล็กน้อย")

    # Previous steps
    prev = signals["prev_steps"].get("value")
    if prev and prev > 15000:
        parts.append(f"เมื่อวานเดินเยอะมาก {prev:,.0f} ก้าว")

    # Streak
    streak = signals.get("streak", 0)
    if streak >= 4:
        parts.append(f"ยิมมา {streak} วันติดแล้ว ควรพัก")
    elif streak >= 3:
        parts.append(f"ยิมมา {streak} วันติด")

    # If nothing notable
    if not parts:
        score = data["readiness"]
        if score >= 70:
            return "วันนี้ร่างกายพร้อม ทุกอย่างปกติดี"
        elif score >= 50:
            return "วันนี้ร่างกายโอเค"
        else:
            return "วันนี้ร่างกายยังไม่ค่อยพร้อม"

    return " · ".join(parts)


def get_today(parquet_dir: str | Path) -> dict[str, Any]:
    """Build the unified /today payload."""
    parquet_dir = Path(parquet_dir)
    today = date.today()
    dow = today.weekday()

    # Gather signals
    hrv_val, hrv_base = _get_today_hrv(parquet_dir)
    rhr_val, rhr_base = _get_today_rhr(parquet_dir)
    prev_steps = _get_prev_steps(parquet_dir)
    streak = _get_gym_streak(parquet_dir)
    sleep_data = _get_sleep(parquet_dir)
    strain_data = _get_today_strain(parquet_dir)

    sleep_hours = sleep_data.get("hours")

    # Compute readiness
    score, label, color, reason = compute_readiness(
        hrv_val, hrv_base, rhr_val, rhr_base,
        prev_steps, streak, sleep_hours, dow,
    )

    # Post-compute adjustments
    extra_reasons = []

    # Late bedtime penalty
    bedtime = sleep_data.get("bedtime")
    if bedtime:
        hour = int(bedtime.split(":")[0])
        if hour >= 1 and hour <= 5:  # slept between 1am-5am
            score -= 10
            extra_reasons.append(f"นอนดึก ({bedtime} น.)")
        elif hour == 0 and int(bedtime.split(":")[1]) >= 30:
            score -= 5

    # Already worked out today — reduce readiness
    if strain_data.get("workouts"):
        score -= 10
        extra_reasons.append("ออกกำลังกายไปแล้ววันนี้")

    if extra_reasons:
        reason = reason + " · " + " · ".join(extra_reasons) if reason != "ร่างกายปกติดี" else " · ".join(extra_reasons)

    score = max(0, min(100, score))

    # Recalculate label/color after adjustments
    if score >= 70:
        label = "พร้อมเต็มที่"
        color = "green"
    elif score >= 50:
        label = "พร้อม"
        color = "green"
    elif score >= 35:
        label = "ระวังหน่อย"
        color = "yellow"
    else:
        label = "ควรพัก"
        color = "red"

    # Recovery (reuse existing module)
    store = HealthStore(parquet_dir)
    recovery_series = compute_recovery_series(store, 7)
    recovery_today = recovery_series[-1] if recovery_series else {}

    # Tip
    already_worked_out = len(strain_data.get("workouts", [])) > 0
    tip = _generate_tip(score, streak, prev_steps, sleep_hours, dow, already_worked_out)

    # Day name in Thai
    thai_days = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]

    payload = {
        "date": str(today),
        "day_th": thai_days[dow],
        "readiness": score,
        "readiness_label": label,
        "color": color,
        "reason": reason,
        "signals": {
            "hrv": {
                "value": round(hrv_val, 1) if hrv_val else None,
                "baseline": round(hrv_base, 1) if hrv_base else None,
                "status": _signal_status(hrv_val, hrv_base, "hrv"),
            },
            "rhr": {
                "value": round(rhr_val, 1) if rhr_val else None,
                "baseline": round(rhr_base, 1) if rhr_base else None,
                "status": _signal_status(rhr_val, rhr_base, "rhr"),
            },
            "sleep": {
                "hours": sleep_hours,
                "quality": sleep_data.get("quality_label", "ไม่มีข้อมูล"),
                "bedtime": sleep_data.get("bedtime"),
                "wakeup": sleep_data.get("wakeup"),
            },
            "prev_steps": {
                "value": round(prev_steps) if prev_steps else None,
                "status": (
                    "good" if prev_steps and prev_steps < 5000
                    else "warning" if prev_steps and prev_steps > 12000
                    else "normal" if prev_steps
                    else "no_data"
                ),
            },
            "streak": streak,
        },
        "strain": strain_data,
        "recovery": {
            "score": recovery_today.get("recovery"),
            "hrv_score": round(recovery_today["hrv_score"] * 100) if recovery_today.get("hrv_score") is not None else None,
            "rhr_score": round(recovery_today["rhr_score"] * 100) if recovery_today.get("rhr_score") is not None else None,
            "sleep_score": round(recovery_today["sleep_score"] * 100) if recovery_today.get("sleep_score") is not None else None,
        },
        "tip": tip,
    }

    # SpO2 + Respiratory Rate (latest today)
    spo2_val = None
    p = parquet_dir / "spo2.parquet"
    if p.exists():
        rows = _query(parquet_dir, f"""
            SELECT value FROM read_parquet('{p.as_posix()}')
            WHERE CAST(start AS DATE) = current_date
            ORDER BY start DESC LIMIT 1
        """)
        if rows and rows[0][0]:
            spo2_val = round(float(rows[0][0]) * 100, 1)  # stored as 0-1

    rr_val = None
    p = parquet_dir / "respiratory_rate.parquet"
    if p.exists():
        rows = _query(parquet_dir, f"""
            SELECT value FROM read_parquet('{p.as_posix()}')
            WHERE CAST(start AS DATE) = current_date
            ORDER BY start DESC LIMIT 1
        """)
        if rows and rows[0][0]:
            rr_val = round(float(rows[0][0]), 1)

    payload["vitals"] = {
        "spo2": spo2_val,
        "rr": rr_val,
    }

    # Weather + Air quality
    payload["weather"] = _get_weather()

    # LLM narration — เล่าเรื่องเท่านั้น ไม่แนะนำ
    from .narrator_llm import narrate_today
    narration = narrate_today(payload)
    if narration:
        payload["reason"] = narration

    return payload
