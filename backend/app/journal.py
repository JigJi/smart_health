"""Daily journal — behavior logging + correlation with biometrics.

Whoop's killer feature: log daily behaviors (alcohol, caffeine, late meal,
hard workout, travel, etc.) then correlate with next-day HRV/RHR to
produce personalized insights like "when you drink alcohol, your HRV
drops 28% the next day."

Storage: simple JSON-lines file (one entry per day). No DB needed.
Correlation: compare next-day HRV/RHR for days WITH vs WITHOUT each tag.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

JOURNAL_FILE = Path(__file__).resolve().parent.parent / "data" / "journal.jsonl"

BEHAVIOR_TAGS = [
    {"id": "alcohol", "label_th": "ดื่มแอลกอฮอล์", "icon": "🍺"},
    {"id": "caffeine_late", "label_th": "กาแฟหลังเที่ยง", "icon": "☕"},
    {"id": "late_meal", "label_th": "กินดึก (หลัง 3 ทุ่ม)", "icon": "🍽️"},
    {"id": "screen_late", "label_th": "ดูจอก่อนนอน", "icon": "📱"},
    {"id": "hard_workout", "label_th": "ออกกำลังกายหนัก", "icon": "💪"},
    {"id": "rest_day", "label_th": "วันพัก (ไม่ออกกำลัง)", "icon": "🛋️"},
    {"id": "travel", "label_th": "เดินทาง/บิน", "icon": "✈️"},
    {"id": "stress", "label_th": "เครียดงาน/ชีวิต", "icon": "😤"},
    {"id": "meditation", "label_th": "นั่งสมาธิ/หายใจ", "icon": "🧘"},
    {"id": "supplement", "label_th": "ทานวิตามิน/supplement", "icon": "💊"},
    {"id": "sick", "label_th": "รู้สึกไม่สบาย", "icon": "🤒"},
    {"id": "good_mood", "label_th": "อารมณ์ดี/มีพลัง", "icon": "😊"},
]


def _load_entries() -> dict[str, dict]:
    """Return {date_str: entry} from journal file."""
    if not JOURNAL_FILE.exists():
        return {}
    entries = {}
    for line in JOURNAL_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        entries[e["day"]] = e
    return entries


def _save_entry(entry: dict) -> None:
    """Append-or-replace entry for a given day."""
    entries = _load_entries()
    entries[entry["day"]] = entry
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_FILE.open("w", encoding="utf-8") as f:
        for d in sorted(entries):
            f.write(json.dumps(entries[d], ensure_ascii=False) + "\n")


def log_day(day: str, tags: list[str], note: str = "") -> dict:
    """Log behaviors for a given day."""
    entry = {
        "day": day,
        "tags": tags,
        "note": note,
    }
    _save_entry(entry)
    return entry


def get_tags() -> list[dict]:
    return BEHAVIOR_TAGS


def get_entries(days: int = 90) -> list[dict]:
    entries = _load_entries()
    cutoff = str(date.today() - timedelta(days=days))
    return [v for k, v in sorted(entries.items()) if k >= cutoff]


def compute_insights(parquet_dir: str | Path) -> list[dict[str, Any]]:
    """Whoop-style journal correlation.

    For each behavior tag, compare NEXT-DAY HRV/RHR on days WITH the tag
    vs days WITHOUT. Uses a simple mean difference + count to surface
    significant patterns.
    """
    entries = _load_entries()
    if len(entries) < 7:
        return [{
            "message_th": f"ข้อมูลยังไม่พอ — บันทึกอย่างน้อย 7 วัน (ตอนนี้มี {len(entries)} วัน)",
            "ready": False,
        }]

    parquet_dir = Path(parquet_dir)
    con = duckdb.connect(":memory:")

    hrv_path = (parquet_dir / "hrv_sdnn.parquet").as_posix()
    rhr_path = (parquet_dir / "resting_heart_rate.parquet").as_posix()

    hrv_by_day: dict[str, float] = {}
    rhr_by_day: dict[str, float] = {}
    try:
        for r in con.execute(
            f"SELECT CAST(start AS DATE), median(value) FROM read_parquet('{hrv_path}') GROUP BY 1"
        ).fetchall():
            hrv_by_day[str(r[0])] = float(r[1])
        for r in con.execute(
            f"SELECT CAST(start AS DATE), avg(value) FROM read_parquet('{rhr_path}') GROUP BY 1"
        ).fetchall():
            rhr_by_day[str(r[0])] = float(r[1])
    except Exception:
        return [{"message_th": "ไม่สามารถอ่านข้อมูล HRV/RHR ได้", "ready": False}]

    all_entry_days = sorted(entries.keys())

    insights: list[dict[str, Any]] = []

    for tag_info in BEHAVIOR_TAGS:
        tag = tag_info["id"]

        with_tag_next_hrv: list[float] = []
        with_tag_next_rhr: list[float] = []
        without_tag_next_hrv: list[float] = []
        without_tag_next_rhr: list[float] = []

        for day_str in all_entry_days:
            next_day = str(date.fromisoformat(day_str) + timedelta(days=1))
            next_hrv = hrv_by_day.get(next_day)
            next_rhr = rhr_by_day.get(next_day)

            has_tag = tag in entries[day_str].get("tags", [])

            if next_hrv is not None:
                if has_tag:
                    with_tag_next_hrv.append(next_hrv)
                else:
                    without_tag_next_hrv.append(next_hrv)
            if next_rhr is not None:
                if has_tag:
                    with_tag_next_rhr.append(next_rhr)
                else:
                    without_tag_next_rhr.append(next_rhr)

        n_with = len(with_tag_next_hrv)
        n_without = len(without_tag_next_hrv)

        if n_with < 3 or n_without < 3:
            continue

        avg_hrv_with = sum(with_tag_next_hrv) / n_with
        avg_hrv_without = sum(without_tag_next_hrv) / n_without
        avg_rhr_with = sum(with_tag_next_rhr) / len(with_tag_next_rhr) if with_tag_next_rhr else None
        avg_rhr_without = sum(without_tag_next_rhr) / len(without_tag_next_rhr) if without_tag_next_rhr else None

        hrv_diff = avg_hrv_with - avg_hrv_without
        hrv_pct = (hrv_diff / avg_hrv_without * 100) if avg_hrv_without else 0
        rhr_diff = (avg_rhr_with - avg_rhr_without) if avg_rhr_with and avg_rhr_without else None

        # Build Thai-language insight
        direction = "ดีขึ้น" if hrv_diff > 0 else "แย่ลง"
        hrv_msg = f"HRV วันถัดไป {direction} {abs(hrv_pct):.0f}% ({avg_hrv_with:.0f} vs {avg_hrv_without:.0f} ms)"
        rhr_msg = ""
        if rhr_diff is not None:
            rhr_dir = "สูงขึ้น" if rhr_diff > 0 else "ต่ำลง"
            rhr_msg = f" · RHR {rhr_dir} {abs(rhr_diff):.1f} bpm"

        impact = "positive" if hrv_diff > 2 else "negative" if hrv_diff < -2 else "neutral"

        insights.append({
            "tag": tag,
            "label_th": tag_info["label_th"],
            "icon": tag_info["icon"],
            "n_with": n_with,
            "n_without": n_without,
            "hrv_with": round(avg_hrv_with, 1),
            "hrv_without": round(avg_hrv_without, 1),
            "hrv_diff_pct": round(hrv_pct, 1),
            "rhr_with": round(avg_rhr_with, 1) if avg_rhr_with else None,
            "rhr_without": round(avg_rhr_without, 1) if avg_rhr_without else None,
            "rhr_diff": round(rhr_diff, 1) if rhr_diff else None,
            "impact": impact,
            "message_th": f"{tag_info['icon']} {tag_info['label_th']} ({n_with} ครั้ง): {hrv_msg}{rhr_msg}",
            "ready": True,
        })

    # Sort by absolute impact
    insights.sort(key=lambda x: abs(x.get("hrv_diff_pct", 0)), reverse=True)
    return insights
