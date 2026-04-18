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
from .recovery import compute_recovery_series, compute_sleep_quality


_target_date_override: str | None = None

def _query(parquet_dir: Path, sql: str) -> list:
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Bangkok'")
    if _target_date_override:
        sql = sql.replace("current_date", f"DATE '{_target_date_override}'")
    return con.execute(sql).fetchall()


def _baseline_stats(prior: list[float]) -> tuple[float | None, float | None]:
    """Return (mean, std) from a prior-days list, or (None, None) if <7 points."""
    if len(prior) < 7:
        return None, None
    m = sum(prior) / len(prior)
    var = sum((x - m) ** 2 for x in prior) / len(prior)
    s = var ** 0.5 or 1.0
    return m, s


def _get_today_hrv(parquet_dir: Path, target: date | None = None) -> tuple[float | None, float | None, float | None]:
    """Return (today_hrv, baseline_mean, baseline_std).

    Clinical standard (Whoop/Oura/Bevel): overnight HRV only — filter to
    early morning hours (before 10am) when Apple Watch logs most resting
    readings post-sleep. Daytime spikes (stress/walking/coffee) are excluded.

    Returning std alongside mean lets callers compute proper z-scores
    (Altini's recommended approach) instead of naive percentage deltas.
    """
    p = parquet_dir / "hrv_sdnn.parquet"
    if not p.exists():
        return None, None, None
    rows = _query(parquet_dir, f"""
        SELECT CAST(start AS DATE) AS d, avg(value) AS v
        FROM read_parquet('{p.as_posix()}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL 90 DAY
          AND EXTRACT(hour FROM start) < 10
        GROUP BY 1 ORDER BY 1
    """)
    if not rows:
        return None, None, None
    by_day = {r[0]: float(r[1]) for r in rows}
    d = target or date.today()
    today_val = by_day.get(d)
    prior = [v for dd, v in by_day.items() if dd < d and (d - dd).days <= 60]
    mean, std = _baseline_stats(prior)
    return today_val, mean, std


def _get_today_rhr(parquet_dir: Path, target: date | None = None) -> tuple[float | None, float | None, float | None]:
    """Return (today_rhr, baseline_mean, baseline_std)."""
    p = parquet_dir / "resting_heart_rate.parquet"
    if not p.exists():
        return None, None, None
    rows = _query(parquet_dir, f"""
        SELECT CAST(start AS DATE) AS d, avg(value) AS v
        FROM read_parquet('{p.as_posix()}')
        WHERE CAST(start AS DATE) >= current_date - INTERVAL 90 DAY
        GROUP BY 1 ORDER BY 1
    """)
    if not rows:
        return None, None, None
    by_day = {r[0]: float(r[1]) for r in rows}
    d = target or date.today()
    today_val = by_day.get(d)
    prior = [v for dd, v in by_day.items() if dd < d and (d - dd).days <= 60]
    mean, std = _baseline_stats(prior)
    return today_val, mean, std


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
            SELECT type,
                   SUM(duration_min) AS dur,
                   SUM(active_kcal) AS kcal,
                   MIN(start) AS first_start
            FROM read_parquet('{p.as_posix()}')
            WHERE CAST(start AS DATE) = current_date
            GROUP BY type
            ORDER BY first_start DESC
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
    """Last night's sleep summary.

    Same data-quality handling as queries.daily_sleep:
    - If this night has modern stages (Core/Deep/REM from iOS 16+ Watch),
      trust those; ignore AsleepUnspecified from other sources to avoid
      double-counting overlapping coverage.
    - Else (legacy night, pre-iOS 16 data): take AsleepUnspecified and
      merge overlapping intervals before summing.

    bedtime/wakeup use the full sleep window (any asleep-ish stage) so
    legacy nights still get sensible anchor times.
    """
    p = parquet_dir / "sleep.parquet"
    if not p.exists():
        return {"hours": None, "quality_label": "ไม่มีข้อมูล"}

    path = p.as_posix()
    window_clause = f"""
        "end" >= current_date - INTERVAL 1 DAY + INTERVAL 20 HOUR
        AND "end" <= current_date + INTERVAL 14 HOUR
        AND CAST("end" AS DATE) = current_date
    """

    # Does this night have any modern stage?
    flag_rows = _query(parquet_dir, f"""
        SELECT MAX(CASE WHEN stage LIKE '%AsleepCore%'
                         OR stage LIKE '%AsleepDeep%'
                         OR stage LIKE '%AsleepREM%'
                        THEN 1 ELSE 0 END) AS has_modern
        FROM read_parquet('{path}')
        WHERE {window_clause}
    """)
    has_modern = bool(flag_rows and flag_rows[0][0] == 1)

    if has_modern:
        # Strict modern-only sum — also break out stages for quality scoring
        rows = _query(parquet_dir, f"""
            SELECT
                min(start) AS bedtime,
                max("end") AS wakeup,
                SUM(CASE WHEN stage LIKE '%AsleepCore%'
                          OR stage LIKE '%AsleepDeep%'
                          OR stage LIKE '%AsleepREM%'
                         THEN EXTRACT(EPOCH FROM ("end" - start)) / 3600.0
                         ELSE 0 END) AS hours,
                SUM(CASE WHEN stage LIKE '%AsleepDeep%'
                         THEN EXTRACT(EPOCH FROM ("end" - start)) / 60.0
                         ELSE 0 END) AS deep_min,
                SUM(CASE WHEN stage LIKE '%AsleepREM%'
                         THEN EXTRACT(EPOCH FROM ("end" - start)) / 60.0
                         ELSE 0 END) AS rem_min,
                SUM(CASE WHEN stage LIKE '%AsleepCore%'
                         THEN EXTRACT(EPOCH FROM ("end" - start)) / 60.0
                         ELSE 0 END) AS core_min,
                SUM(CASE WHEN stage LIKE '%Awake%'
                         THEN EXTRACT(EPOCH FROM ("end" - start)) / 60.0
                         ELSE 0 END) AS awake_min
            FROM read_parquet('{path}')
            WHERE {window_clause}
        """)
    else:
        # Legacy: interval-merge AsleepUnspecified to collapse duplicate coverage
        rows = _query(parquet_dir, f"""
            WITH legacy AS (
              SELECT start, "end"
              FROM read_parquet('{path}')
              WHERE {window_clause} AND stage LIKE '%Asleep%'
            ),
            ordered AS (
              SELECT start, "end",
                     MAX("end") OVER (ORDER BY start
                                      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_end
              FROM legacy
            ),
            islands AS (
              SELECT start, "end",
                     SUM(CASE WHEN prev_end IS NULL OR start > prev_end THEN 1 ELSE 0 END)
                       OVER (ORDER BY start) AS grp
              FROM ordered
            ),
            merged AS (
              SELECT MIN(start) AS s, MAX("end") AS e
              FROM islands GROUP BY grp
            )
            SELECT MIN(s) AS bedtime,
                   MAX(e) AS wakeup,
                   SUM(EXTRACT(EPOCH FROM (e - s)) / 3600.0) AS hours
            FROM merged
        """)

    if not rows or rows[0][2] is None or float(rows[0][2]) == 0:
        return {"hours": None, "quality_label": "ไม่มีข้อมูล", "sleep_quality_pct": None}

    hours = round(float(rows[0][2]), 1)
    bedtime = rows[0][0]
    wakeup = rows[0][1]

    # Stage breakdown (modern nights only, legacy = None)
    deep_min = round(float(rows[0][3]), 1) if has_modern and len(rows[0]) > 3 and rows[0][3] else None
    rem_min = round(float(rows[0][4]), 1) if has_modern and len(rows[0]) > 4 and rows[0][4] else None
    core_min = round(float(rows[0][5]), 1) if has_modern and len(rows[0]) > 5 and rows[0][5] else None
    awake_min = round(float(rows[0][6]), 1) if has_modern and len(rows[0]) > 6 and rows[0][6] else None

    # ── Quality-aware sleep score (0-100) ──
    # Combines duration + stage quality + efficiency + bedtime regularity.
    # This replaces the old hours-only label system.
    sleep_quality_pct = compute_sleep_quality(
        hours, deep_min, rem_min, awake_min,
        bedtime.strftime("%H:%M") if bedtime else None,
    )

    # Label now reflects quality, not just hours
    if sleep_quality_pct is not None:
        if sleep_quality_pct >= 80:
            label = "ดีมาก"
        elif sleep_quality_pct >= 65:
            label = "พอดี"
        elif sleep_quality_pct >= 45:
            label = "น้อยไป"
        else:
            label = "น้อยมาก"
    else:
        # Fallback for legacy nights without stage data
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
        "deep_min": deep_min,
        "rem_min": rem_min,
        "core_min": core_min,
        "awake_min": awake_min,
        "sleep_quality_pct": sleep_quality_pct,
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

    # RHR signal — smooth gradient to avoid cliff at exactly diff=-3
    # (0.5 bpm difference used to swing score by 10 points)
    if rhr is not None and rhr_base is not None:
        diff = rhr - rhr_base
        if diff <= -4:
            score += 10
        elif diff <= -2:
            score += 6
        elif diff <= -1:
            score += 3
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


def _compute_tips(
    parquet_dir: Path,
    hrv_val: float | None, hrv_base: float | None,
    rhr_val: float | None, rhr_base: float | None,
    sleep_hours: float | None, bedtime: str | None,
    workouts_today: list, streak: int,
    prev_steps: float | None,
) -> list[dict[str, Any]]:
    """Data-driven suggestions (active mode — user opts in to see them).

    Personalized: uses user's own workout history. Options pulled from
    what they actually did on similar-state days, not generic advice.
    Returns 0-3 tips prioritized by severity.
    """
    from datetime import datetime
    from .personal_tips import (
        build_activity_profile,
        personalize_recovery_tip,
        personalize_performance_tip,
    )

    tips: list[dict[str, Any]] = []
    now = datetime.now()
    now_hour = now.hour
    is_weekend = now.weekday() >= 5  # 5=Sat, 6=Sun

    hrv_pct = ((hrv_val - hrv_base) / hrv_base * 100) if (hrv_val and hrv_base) else None
    has_workout = len(workouts_today) > 0

    # Build user profile once (cached nowhere — runs per request; fast on parquet)
    profile = build_activity_profile(parquet_dir)

    has_history = profile.get("has_exercise_history", False)

    # Rule 1: HRV warning → recovery tip (personalized OR gentle wellness for no-history users)
    # No time-of-day gate — HRV signal valid anytime, user judges intensity themselves
    if hrv_pct is not None and hrv_pct <= -15 and not has_workout:
        if has_history:
            personal = personalize_recovery_tip(profile, is_weekend)
            if personal:
                personal["headline"] = f"ออกกำลังเบาๆ หรือพัก (HRV ต่ำกว่าปกติ {abs(int(hrv_pct))}%)"
                tips.append(personal)
        else:
            # Sedentary / new user: gentle non-workout advice
            tips.append({
                "category": "recovery_general",
                "headline": f"ฟังร่างกายวันนี้ (HRV ต่ำกว่าปกติ {abs(int(hrv_pct))}%)",
                "options": [
                    "เดินสั้นๆ 10–15 นาที ถ้ามีเวลา",
                    "ดื่มน้ำให้พอ หลีกเลี่ยงคาเฟอีนตอนเย็น",
                    "พยายามเข้านอนเร็วคืนนี้",
                ],
            })

    # Rule 2: Overtraining signal — only applies if has workout history
    elif hrv_pct is not None and hrv_pct <= -8 and streak >= 3 and has_history:
        personal = personalize_recovery_tip(profile, is_weekend)
        if personal:
            personal["headline"] = f"พักให้ระบบประสาท reset (ออกกำลังติด {streak} วัน + HRV ลง)"
            tips.append(personal)

    # Rule 3: High HRV → performance tip (only for users with exercise history)
    elif hrv_pct is not None and hrv_pct >= 10 and not has_workout and streak <= 2 and has_history:
        personal = personalize_performance_tip(profile, is_weekend)
        if personal:
            personal["headline"] = f"ออกกำลังเต็มที่ได้ (HRV สูงกว่าปกติ {int(hrv_pct)}%)"
            tips.append(personal)

    # Rule 4: Late bedtime pattern + HRV dip
    if bedtime and hrv_pct is not None and hrv_pct < -5:
        try:
            bt_h = int(bedtime.split(':')[0])
            bt_m = int(bedtime.split(':')[1])
            is_late = (1 <= bt_h <= 5) or (bt_h == 0 and bt_m >= 30)
            if is_late:
                tips.append({
                    "category": "sleep",
                    "headline": f"เข้านอนเร็วขึ้น (เข้านอน {bedtime} + HRV ต่ำ)",
                    "options": [
                        "คืนนี้ลองเข้านอน 23:00–23:30",
                        "HRV มักดีขึ้นภายใน 1 คืน ถ้าปรับจังหวะการนอนได้",
                        "ปิดจอก่อนนอน 30 นาที ช่วยให้ร่างกายง่วงเร็วขึ้น",
                    ],
                })
        except (ValueError, IndexError):
            pass

    # Rule 5: Short sleep + early/mid-day → nap opportunity
    if sleep_hours is not None and sleep_hours < 6 and 11 <= now_hour <= 15:
        tips.append({
            "category": "sleep",
            "headline": f"งีบชดเชย (นอนแค่ {sleep_hours} ชม. เมื่อคืน)",
            "options": [
                "งีบ 20–30 นาที ก่อนบ่าย 3 โมง",
                "ช่วยให้ HRV และความตื่นตัวดีขึ้นชัดเจน",
                "ถ้านานเกิน 30 นาที จะหลับลึก ตื่นมาจะงง",
            ],
        })

    # Rule 6: Low movement + afternoon
    if prev_steps is not None and prev_steps < 3000 and 15 <= now_hour <= 20 and not has_workout:
        tips.append({
            "category": "habit",
            "headline": "เดินสั้นๆ (เคลื่อนไหวน้อยเมื่อวาน)",
            "options": [
                "เดิน 15–20 นาที ไม่ต้องวางแผนอะไรมาก",
                "ช่วยการไหลเวียนเลือด ดีกว่านั่งอยู่นิ่งๆ",
            ],
        })

    # Rule 7: Everything green + streak 0-1 → kickstart (has_history only)
    # 9–21 = generous window to include late-chronotype users
    if (hrv_pct is not None and hrv_pct >= 0 and
        not has_workout and streak == 0 and 9 <= now_hour <= 21 and has_history):
        top = profile.get("top_types", [])[:3]
        tips.append({
            "category": "habit_personal",
            "headline": "กลับมาเคลื่อนไหว (ไม่ได้ออกกำลังมาสักพัก + ฟื้นตัวดี)",
            "options": [name for name, _ in top],
        })

    # Cap at 3 tips — too many dilutes signal
    return tips[:3]


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

    # Sleep — mention duration, quality, and fragmentation issues
    sleep_h = signals["sleep"].get("hours")
    bedtime = signals["sleep"].get("bedtime")
    deep_min = signals["sleep"].get("deep_min")
    awake_min = signals["sleep"].get("awake_min")
    if sleep_h is not None and bedtime:
        hour = int(bedtime.split(":")[0])
        if sleep_h < 5:
            parts.append(f"เมื่อคืนนอนตี {hour} นอนจริงแค่ {sleep_h:.0f} ชั่วโมง")
        elif sleep_h < 6:
            parts.append(f"เมื่อคืนนอน {sleep_h:.0f} ชั่วโมง น้อยไปหน่อย")
        elif hour >= 1 and hour <= 4:
            parts.append(f"เมื่อคืนนอนดึก แต่นอนได้ {sleep_h:.0f} ชั่วโมง")

        # Deep sleep warning (clinical target: ≥60 min)
        if deep_min is not None and deep_min < 30:
            parts.append(f"หลับลึกแค่ {deep_min:.0f} นาที")
        elif deep_min is not None and deep_min < 45:
            parts.append(f"หลับลึกน้อย ({deep_min:.0f} นาที)")

        # Fragmented sleep warning (woke up a lot)
        if awake_min is not None and awake_min >= 30:
            parts.append(f"ตื่นระหว่างคืนรวม {awake_min:.0f} นาที")

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


def get_today(parquet_dir: str | Path, target_date: str | None = None) -> dict[str, Any]:
    """Build the unified /today payload. If target_date given (YYYY-MM-DD), show that day."""
    parquet_dir = Path(parquet_dir)
    if target_date:
        today = date.fromisoformat(target_date)
    else:
        today = date.today()
    dow = today.weekday()

    # Set date override for SQL queries
    global _target_date_override
    _target_date_override = target_date

    # Gather signals
    hrv_val, hrv_base, hrv_std = _get_today_hrv(parquet_dir, today)
    rhr_val, rhr_base, rhr_std = _get_today_rhr(parquet_dir, today)
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

    # Post-compute adjustments — apply for ALL days (today & past) so that
    # a day's readiness is an immutable fact of that day, not affected by
    # when it's being viewed. Late bedtime + "already worked out" are real
    # factors that were true on that day and should persist in history.
    extra_reasons = []

    # Late bedtime penalty
    bedtime = sleep_data.get("bedtime")
    if bedtime:
        hour = int(bedtime.split(":")[0])
        if hour >= 1 and hour <= 5:
            score -= 10
            extra_reasons.append(f"นอนดึก ({bedtime} น.)")
        elif hour == 0 and int(bedtime.split(":")[1]) >= 30:
            score -= 5

    # Already worked out that day — reduce readiness proportional to intensity.
    # Flat -10 was unfair: a 100-kcal walk shouldn't cost the same as a
    # 700-kcal weights+cardio session. Smooth linear gradient (per memory
    # feedback_no_threshold_cliffs): 0 kcal → -5, 500 kcal → -15, 1000+ kcal → -25.
    if strain_data.get("workouts"):
        today_kcal = strain_data.get("active_kcal", 0) or 0
        penalty = min(25, 5 + today_kcal * 0.02)
        score -= round(penalty)
        if today_kcal >= 500:
            extra_reasons.append(f"ออกกำลังหนักแล้ววันนี้ ({today_kcal:.0f} kcal)")
        elif today_kcal >= 200:
            extra_reasons.append(f"ออกกำลังไปแล้ววันนี้ ({today_kcal:.0f} kcal)")
        else:
            extra_reasons.append("ออกกำลังเบาๆ ไปแล้ววันนี้")

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

    # Recovery — Altini-style z-score mapping, aligned with recovery.py:
    #   Map z-score to 0..1 (cap at ±2σ) → weighted by HRV 0.55 / RHR 0.25 / Sleep 0.20.
    # Previously used a naive linear %-diff which diverged from compute_recovery_series
    # (debug_recovery.py output). Unified on the Altini path as single source of truth.
    from .recovery import _zscore_to_unit, W_HRV, W_RHR, W_SLEEP, SLEEP_TARGET_MIN

    hrv_score: float | None = None
    rhr_score: float | None = None
    sleep_score: float | None = None

    if hrv_val is not None and hrv_base is not None and hrv_std:
        hrv_score = _zscore_to_unit((hrv_val - hrv_base) / hrv_std)

    if rhr_val is not None and rhr_base is not None and rhr_std:
        # Lower RHR is better → invert sign.
        rhr_score = _zscore_to_unit((rhr_base - rhr_val) / rhr_std)

    if sleep_hours is not None:
        # Use quality-aware score if available, otherwise fall back to duration-only
        sleep_quality = sleep_data.get("sleep_quality_pct")
        if sleep_quality is not None:
            sleep_score = sleep_quality / 100.0
        else:
            sleep_score = min(1.0, (sleep_hours * 60) / SLEEP_TARGET_MIN)

    # Weighted combine, re-normalizing if a component is missing.
    parts: list[tuple[float, float]] = []
    if hrv_score is not None:   parts.append((hrv_score, W_HRV))
    if rhr_score is not None:   parts.append((rhr_score, W_RHR))
    if sleep_score is not None: parts.append((sleep_score, W_SLEEP))

    recovery_score: int | None = None
    if parts:
        total_w = sum(w for _, w in parts)
        recovery_score = round(100 * sum(s * w for s, w in parts) / total_w)

    # Keep UI-facing component scores as 0-100 (same scale as recovery_score)
    hrv_pct = round(hrv_score * 100) if hrv_score is not None else None
    rhr_pct = round(rhr_score * 100) if rhr_score is not None else None
    sleep_pct = round(sleep_score * 100) if sleep_score is not None else None

    # Strain decay: morning signals can say "well recovered" yet the user
    # is depleted by afternoon after heavy training. Recovery is a PHYSIOLOGICAL
    # state, not a morning forecast — if the body has done work since waking,
    # the score must reflect that. Smooth decay up to 30%: 0 kcal → 0%,
    # 500 kcal → 15%, 1000+ kcal → 30% (capped).
    if recovery_score is not None and strain_data.get("workouts"):
        today_kcal = strain_data.get("active_kcal", 0) or 0
        decay_pct = min(0.30, today_kcal / 1000 * 0.30)
        recovery_score = round(recovery_score * (1 - decay_pct))

    # Tip
    already_worked_out = len(strain_data.get("workouts", [])) > 0
    tip = _generate_tip(score, streak, prev_steps, sleep_hours, dow, already_worked_out)

    # Altini-style stress summary (acute / weekly trend / CV stability).
    # Passes today's workout kcal so stress includes physical load, not just
    # autonomic — morning HRV can say "recovered" while body is depleted from
    # a big gym session. Altini's HRV alone misses that; we combine.
    from .stress import compute_stress
    stress_data = compute_stress(
        parquet_dir, today,
        today_kcal=strain_data.get("active_kcal"),
        bedtime=sleep_data.get("bedtime"),
    )

    # Altini-style illness watcher — multi-signal anomaly for today
    from .illness import detect_today as detect_illness_today
    illness_data = detect_illness_today(parquet_dir, today)

    # Data-driven tips (active mode — user opts in by tapping to expand)
    tips = _compute_tips(
        parquet_dir,
        hrv_val, hrv_base, rhr_val, rhr_base,
        sleep_hours, sleep_data.get("bedtime"),
        strain_data.get("workouts", []), streak,
        prev_steps,
    )

    # Illness takes precedence — prepend as Rule 0 if confidence ≥ medium.
    # Low confidence (single signal) stays silent to avoid false-alarm fatigue.
    if illness_data.get("confidence") in ("medium", "high"):
        illness_tip = {
            "category": "illness",
            "headline": illness_data["headline"],
            "options": [s["msg"] for s in illness_data.get("signals", [])]
                       + (["พบต่อเนื่อง 2 วัน"] if illness_data.get("sustained") else []),
        }
        tips = [illness_tip] + tips[:2]  # keep at most 3 total
    # Track whether tips are based on user's own history
    tips_personalized = any(t.get("category", "").endswith("_personal") for t in tips)

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
                "deep_min": sleep_data.get("deep_min"),
                "rem_min": sleep_data.get("rem_min"),
                "awake_min": sleep_data.get("awake_min"),
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
            "score": recovery_score,
            "hrv_score": hrv_pct,
            "rhr_score": rhr_pct,
            "sleep_score": sleep_pct,
        },
        # Top-level sleep alias for consumers that don't walk into signals.*
        # (same values, just convenience — mirrors `strain` + `recovery` siblings)
        "sleep": sleep_data,
        "stress": stress_data,
        "illness": illness_data,
        "tip": tip,
        "tips": tips,
        "tips_personalized": tips_personalized,
    }

    # SpO2 + Respiratory Rate — average across today's samples
    # (clinical standard; "latest" is misleading because one stray 100% reading
    # would show 100% even if average was 97%)
    spo2_val = None
    p = parquet_dir / "spo2.parquet"
    if p.exists():
        rows = _query(parquet_dir, f"""
            SELECT avg(value) FROM read_parquet('{p.as_posix()}')
            WHERE CAST(start AS DATE) = current_date
        """)
        if rows and rows[0][0]:
            spo2_val = round(float(rows[0][0]) * 100, 1)  # stored as 0-1

    rr_val = None
    p = parquet_dir / "respiratory_rate.parquet"
    if p.exists():
        rows = _query(parquet_dir, f"""
            SELECT avg(value) FROM read_parquet('{p.as_posix()}')
            WHERE CAST(start AS DATE) = current_date
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
    else:
        # Fallback — strip numbers from template reason
        import re
        payload["reason"] = re.sub(r'\d+[\d,.]*\s*(?:ms|bpm|ก้าว|ชม\.|%)', '', payload["reason"])
        payload["reason"] = re.sub(r'\(\s*\)', '', payload["reason"]).strip()
        if not payload["reason"]:
            payload["reason"] = "ร่างกายอยู่ในเกณฑ์ปกติ"

    _target_date_override = None
    return payload


def get_calendar_month(parquet_dir: str | Path, year: int, month: int) -> dict[str, Any]:
    """Return daily readiness scores for a specific month."""
    import calendar as cal_mod
    parquet_dir = Path(parquet_dir)
    today = date.today()
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='Asia/Bangkok'")

    first_day = date(year, month, 1)
    last_day = date(year, month, cal_mod.monthrange(year, month)[1])

    def _cal_query(sql: str) -> list:
        return con.execute(sql).fetchall()

    hrv_by_day: dict = {}
    rhr_by_day: dict = {}
    steps_by_day: dict = {}
    sleep_by_day: dict = {}
    workout_days: set = set()

    # Load data covering this month + 60 days before for baseline
    start_str = str(first_day - timedelta(days=60))
    end_str = str(last_day)

    hrv_p = parquet_dir / "hrv_sdnn.parquet"
    rhr_p = parquet_dir / "resting_heart_rate.parquet"
    steps_p = parquet_dir / "steps.parquet"
    sleep_p = parquet_dir / "sleep.parquet"
    workouts_p = parquet_dir / "workouts.parquet"

    if hrv_p.exists():
        rows = _cal_query(f"""
            SELECT CAST(start AS DATE) AS d, median(value) AS v
            FROM read_parquet('{hrv_p.as_posix()}')
            WHERE CAST(start AS DATE) >= DATE '{start_str}'
              AND CAST(start AS DATE) <= DATE '{end_str}'
            GROUP BY 1 ORDER BY 1
        """)
        hrv_by_day = {r[0]: float(r[1]) for r in rows if r[1]}

    if rhr_p.exists():
        rows = _cal_query(f"""
            SELECT CAST(start AS DATE) AS d, avg(value) AS v
            FROM read_parquet('{rhr_p.as_posix()}')
            WHERE CAST(start AS DATE) >= DATE '{start_str}'
              AND CAST(start AS DATE) <= DATE '{end_str}'
            GROUP BY 1 ORDER BY 1
        """)
        rhr_by_day = {r[0]: float(r[1]) for r in rows if r[1]}

    if steps_p.exists():
        rows = _cal_query(f"""
            SELECT CAST(start AS DATE) AS d, sum(value) AS v
            FROM read_parquet('{steps_p.as_posix()}')
            WHERE CAST(start AS DATE) >= DATE '{str(first_day - timedelta(days=1))}'
              AND CAST(start AS DATE) <= DATE '{end_str}'
            GROUP BY 1
        """)
        steps_by_day = {r[0]: float(r[1]) for r in rows if r[1]}

    bedtime_by_day: dict = {}
    if sleep_p.exists():
        rows = _cal_query(f"""
            SELECT CAST("end" AS DATE) AS d,
                   SUM(CASE WHEN stage LIKE '%AsleepCore%' OR stage LIKE '%AsleepDeep%'
                            OR stage LIKE '%AsleepREM%' THEN
                       EXTRACT(EPOCH FROM ("end" - start)) / 3600.0 ELSE 0 END) AS hours,
                   min(start) AS bedtime
            FROM read_parquet('{sleep_p.as_posix()}')
            WHERE CAST("end" AS DATE) >= DATE '{str(first_day)}'
              AND CAST("end" AS DATE) <= DATE '{end_str}'
            GROUP BY 1
        """)
        sleep_by_day = {r[0]: float(r[1]) for r in rows if r[1] and float(r[1]) > 0}
        bedtime_by_day = {r[0]: r[2] for r in rows if r[2]}

    if workouts_p.exists():
        rows = _cal_query(f"""
            SELECT DISTINCT CAST(start AS DATE) AS d
            FROM read_parquet('{workouts_p.as_posix()}')
            WHERE CAST(start AS DATE) >= DATE '{str(first_day - timedelta(days=14))}'
              AND CAST(start AS DATE) <= DATE '{end_str}'
        """)
        workout_days = {r[0] for r in rows}

    days_in_month = cal_mod.monthrange(year, month)[1]
    results = []
    for day_num in range(1, days_in_month + 1):
        d = date(year, month, day_num)
        if d > today:
            results.append({"date": str(d), "score": None, "color": "none", "has_workout": False})
            continue

        prior_hrv = [v for dd, v in hrv_by_day.items() if dd < d and (d - dd).days <= 60]
        prior_rhr = [v for dd, v in rhr_by_day.items() if dd < d and (d - dd).days <= 60]

        hrv_val = hrv_by_day.get(d)
        rhr_val = rhr_by_day.get(d)
        hrv_base = sum(prior_hrv) / len(prior_hrv) if len(prior_hrv) >= 7 else None
        rhr_base = sum(prior_rhr) / len(prior_rhr) if len(prior_rhr) >= 7 else None
        prev_steps = steps_by_day.get(d - timedelta(days=1))
        sleep_hours = sleep_by_day.get(d)

        streak = 0
        for j in range(1, 15):
            if (d - timedelta(days=j)) in workout_days:
                streak += 1
            else:
                break

        score, label, color, reason = compute_readiness(
            hrv_val, hrv_base, rhr_val, rhr_base,
            prev_steps, streak, sleep_hours, d.weekday(),
        )

        # Apply /today's post-compute penalties for every day so calendar
        # matches dashboard readiness — day's readiness is immutable history
        bt = bedtime_by_day.get(d)
        if bt:
            h, m = bt.hour, bt.minute
            if 1 <= h <= 5:
                score -= 10
            elif h == 0 and m >= 30:
                score -= 5

        if d in workout_days:
            score -= 10

        # Clamp + recompute color (match /today thresholds)
        score = max(0, min(100, score))
        if score >= 50:
            color = "green"
        elif score >= 35:
            color = "yellow"
        else:
            color = "red"

        results.append({
            "date": str(d),
            "score": score,
            "color": color,
            "has_workout": d in workout_days,
        })

    thai_months = ['','ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.','ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.']
    return {
        "year": year,
        "month": month,
        "month_th": thai_months[month],
        "first_weekday": first_day.weekday(),  # 0=Mon
        "days": results,
    }
