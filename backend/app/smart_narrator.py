"""Smart Narrator — personalized daily assessment in natural Thai.

Uses the personal profile to generate context-aware messages that feel
like a friend who knows your body. Not generic rules — YOUR patterns.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from .personal_profile import build_profile


_PROFILE_CACHE: dict[str, Any] | None = None


def _get_profile(parquet_dir: Path) -> dict[str, Any]:
    global _PROFILE_CACHE
    if _PROFILE_CACHE is None:
        _PROFILE_CACHE = build_profile(parquet_dir)
    return _PROFILE_CACHE


def narrate_day(parquet_dir: str | Path, target: str | None = None) -> dict[str, Any]:
    """Generate a personalized assessment for a given day."""
    pq = Path(parquet_dir)
    profile = _get_profile(pq)
    con = duckdb.connect(":memory:")

    d = date.fromisoformat(target) if target else date.today()
    dow_name = d.strftime("%a")

    hrv_path = (pq / "hrv_sdnn.parquet").as_posix()
    rhr_path = (pq / "resting_heart_rate.parquet").as_posix()
    wk_path = (pq / "workouts.parquet").as_posix()
    hr_path = (pq / "heart_rate.parquet").as_posix()

    # Today's data
    hrv_row = con.execute(f"""
        SELECT median(value), count(*) FROM read_parquet('{hrv_path}')
        WHERE CAST(start AS DATE) = DATE '{d}'
    """).fetchone()
    rhr_row = con.execute(f"""
        SELECT avg(value) FROM read_parquet('{rhr_path}')
        WHERE CAST(start AS DATE) = DATE '{d}'
    """).fetchone()
    wk_rows = con.execute(f"""
        SELECT REPLACE(type, 'HKWorkoutActivityType', '') AS sport,
               duration_min, hr_avg
        FROM read_parquet('{wk_path}')
        WHERE CAST(start AS DATE) = DATE '{d}'
        ORDER BY duration_min DESC
    """).fetchall()
    hr_n = con.execute(f"""
        SELECT count(*) FROM read_parquet('{hr_path}')
        WHERE CAST(start AS DATE) = DATE '{d}'
    """).fetchone()[0]

    # Yesterday's data for context
    prev_d = d - timedelta(days=1)
    prev_hrv = con.execute(f"""
        SELECT median(value) FROM read_parquet('{hrv_path}')
        WHERE CAST(start AS DATE) = DATE '{prev_d}'
    """).fetchone()[0]
    prev_wk = con.execute(f"""
        SELECT count(*) FROM read_parquet('{wk_path}')
        WHERE CAST(start AS DATE) = DATE '{prev_d}'
    """).fetchone()[0]

    # 60-day baseline
    base_hrv = con.execute(f"""
        SELECT avg(value), stddev_pop(value) FROM read_parquet('{hrv_path}')
        WHERE CAST(start AS DATE) BETWEEN DATE '{d}' - INTERVAL 60 DAY AND DATE '{d}' - INTERVAL 1 DAY
    """).fetchone()
    base_rhr = con.execute(f"""
        SELECT avg(value), stddev_pop(value) FROM read_parquet('{rhr_path}')
        WHERE CAST(start AS DATE) BETWEEN DATE '{d}' - INTERVAL 60 DAY AND DATE '{d}' - INTERVAL 1 DAY
    """).fetchone()

    hrv = float(hrv_row[0]) if hrv_row and hrv_row[0] else None
    rhr = float(rhr_row[0]) if rhr_row and rhr_row[0] else None
    hrv_z = None
    rhr_z = None
    if hrv and base_hrv[0] and base_hrv[1]:
        hrv_z = (hrv - base_hrv[0]) / (base_hrv[1] or 1)
    if rhr and base_rhr[0] and base_rhr[1]:
        rhr_z = (rhr - base_rhr[0]) / (base_rhr[1] or 1)

    # Build narratives
    messages: list[str] = []
    tags: list[str] = []  # state tags for the frontend

    if hr_n == 0:
        return _build_result(d, "no_data", ["ไม่ได้ใส่ Watch วันนี้"], [], profile, hrv, rhr, wk_rows)
    if hr_n < 100:
        return _build_result(d, "low_confidence", [
            f"ใส่ Watch แค่ {hr_n} samples — ยังประเมินไม่ได้"
        ], [], profile, hrv, rhr, wk_rows)

    # --- Personalized day-of-week context ---
    dow_hrv_data = {x["dow"]: x["hrv"] for x in profile["dow_baselines"]["hrv"]}
    dow_expected = dow_hrv_data.get(dow_name)
    if dow_expected and hrv:
        diff = hrv - dow_expected
        if abs(diff) > 5:
            if diff > 0:
                messages.append(
                    f"HRV {hrv:.0f} ms สูงกว่าวัน{_dow_th(dow_name)}ปกติของคุณ ({dow_expected:.0f} ms) — วันนี้ร่างกายอยู่ในจุดที่ดี"
                )
                tags.append("above_dow")
            else:
                messages.append(
                    f"HRV {hrv:.0f} ms ต่ำกว่าวัน{_dow_th(dow_name)}ปกติของคุณ ({dow_expected:.0f} ms) — อาจมีอะไรกดดัน"
                )
                tags.append("below_dow")
        else:
            messages.append(
                f"HRV {hrv:.0f} ms ใกล้เคียงวัน{_dow_th(dow_name)}ปกติของคุณ ({dow_expected:.0f} ms)"
            )

    # --- RHR context ---
    if rhr and rhr_z is not None:
        if rhr_z >= 1.5:
            messages.append(
                f"RHR {rhr:.0f} bpm สูงผิดปกติ (ปกติ ~{base_rhr[0]:.0f}) — ระบบประสาทถูกกดดัน"
            )
            tags.append("rhr_high")
        elif rhr_z >= 1.0:
            messages.append(f"RHR {rhr:.0f} bpm สูงกว่าปกติเล็กน้อย")
            tags.append("rhr_elevated")
        elif rhr_z <= -1.0:
            messages.append(f"RHR {rhr:.0f} bpm ต่ำกว่าปกติ — หัวใจทำงานมีประสิทธิภาพวันนี้")
            tags.append("rhr_low")

    # --- Post-workout recovery context ---
    if prev_wk and prev_wk > 0 and hrv:
        messages.append(
            f"เมื่อวานออกกำลังกาย — จากประวัติของคุณ ร่างกายใช้เวลา recover ~1 วัน"
        )
        if hrv_z is not None and hrv_z < -0.5:
            messages.append("HRV ยังไม่กลับ baseline — อาจต้องการพักเพิ่ม")
            tags.append("still_recovering")

    # --- Workout today ---
    if wk_rows:
        sport = wk_rows[0][0]
        dur = wk_rows[0][1]
        messages.append(f"วันนี้ออกกำลัง {sport} {dur:.0f} นาที")
        tags.append("trained")

        # Check recovery curve for this sport
        sport_recovery = next(
            (r for r in profile["recovery_by_sport"] if r["sport"] == sport), None
        )
        if sport_recovery:
            rec_days = sport_recovery["recovery_days"]
            if rec_days >= 2:
                messages.append(
                    f"จากประวัติ {sport} ร่างกายคุณใช้เวลา {rec_days} วัน recover — พรุ่งนี้ควรเบาลง"
                )
            else:
                messages.append(
                    f"จากประวัติ {sport} คุณ recover ภายใน 1 วัน — พรุ่งนี้พร้อม"
                )

    # --- Weekly load context ---
    # Count workouts this week
    week_start = d - timedelta(days=d.weekday())
    wk_this_week = con.execute(f"""
        SELECT count(DISTINCT CAST(start AS DATE))
        FROM read_parquet('{wk_path}')
        WHERE CAST(start AS DATE) BETWEEN DATE '{week_start}' AND DATE '{d}'
    """).fetchone()[0]

    optimal = profile.get("optimal_load")
    if optimal and wk_this_week:
        sweet = optimal["best_sessions_per_week"]
        if wk_this_week >= sweet + 1:
            messages.append(
                f"สัปดาห์นี้ออกกำลังไปแล้ว {wk_this_week} ครั้ง — sweet spot ของคุณคือ {sweet} ครั้ง/สัปดาห์ ระวังอย่า overdo"
            )
            tags.append("over_sweet_spot")
        elif wk_this_week == sweet:
            messages.append(
                f"สัปดาห์นี้ครบ {sweet} sessions แล้ว — ถึง sweet spot ของคุณพอดี 🎯"
            )
            tags.append("at_sweet_spot")

    # --- Seasonal context ---
    seasonal = profile.get("seasonal")
    if seasonal:
        month_names_th = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                          "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
        current_month = month_names_th[d.month]
        if current_month == seasonal["worst_month"]:
            messages.append(
                f"เดือน{current_month}เป็นเดือนที่ HRV คุณต่ำสุดในรอบปี (avg {seasonal['worst_hrv']} ms) — ดูแลตัวเองเป็นพิเศษ"
            )
            tags.append("worst_season")

    # --- Determine overall state ---
    state = _determine_state(hrv_z, rhr_z, tags)

    return _build_result(d, state, messages, tags, profile, hrv, rhr, wk_rows)


def _determine_state(hrv_z, rhr_z, tags) -> str:
    if "rhr_high" in tags and "below_dow" in tags:
        return "stressed"
    if "still_recovering" in tags:
        return "tired"
    if "rhr_high" in tags:
        return "under_recovered"
    if "above_dow" in tags and ("rhr_low" in tags or "trained" not in tags):
        return "peak"
    if "above_dow" in tags:
        return "energized"
    if "trained" in tags:
        return "active_day"
    if hrv_z is not None and hrv_z >= 0.3:
        return "energized"
    return "normal"


STATES_META = {
    "peak": ("⚡", "พร้อมสุด", "#5be49b"),
    "energized": ("😊", "สดใส มีพลัง", "#34d399"),
    "normal": ("👍", "ปกติดี", "#94a3b8"),
    "active_day": ("💪", "วันออกกำลัง", "#60a5fa"),
    "stressed": ("😤", "เครียด", "#f59e0b"),
    "tired": ("😴", "เหนื่อยสะสม", "#a78bfa"),
    "under_recovered": ("😵", "ฟื้นตัวไม่ทัน", "#ef5350"),
    "no_data": ("⚪", "ไม่ได้ใส่ Watch", "#334155"),
    "low_confidence": ("❓", "ข้อมูลไม่พอ", "#475569"),
}


def _build_result(d, state, messages, tags, profile, hrv, rhr, wk_rows):
    emoji, label, color = STATES_META.get(state, ("❓", state, "#94a3b8"))
    return {
        "day": str(d),
        "dow": d.strftime("%a"),
        "state": state,
        "emoji": emoji,
        "label_th": label,
        "color": color,
        "messages_th": messages,
        "tags": tags,
        "hrv_ms": round(hrv, 1) if hrv else None,
        "rhr_bpm": round(rhr, 1) if rhr else None,
        "workouts": [{"sport": w[0], "min": w[1], "hr_avg": w[2]} for w in wk_rows],
        "profile_summary": {
            "sweet_spot": profile.get("optimal_load", {}).get("best_sessions_per_week"),
            "best_dow": profile["dow_baselines"]["best_hrv_day"],
            "worst_dow": profile["dow_baselines"]["worst_hrv_day"],
        },
    }


DOW_TH = {"Mon": "จันทร์", "Tue": "อังคาร", "Wed": "พุธ", "Thu": "พฤหัสบดี",
           "Fri": "ศุกร์", "Sat": "เสาร์", "Sun": "อาทิตย์"}


def _dow_th(dow: str) -> str:
    return DOW_TH.get(dow, dow)
