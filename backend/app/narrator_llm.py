"""LLM-powered Thai health narrator via OpenRouter."""

from __future__ import annotations

import os
import json
from typing import Any
from pathlib import Path

import ssl
import urllib.request
import urllib.error

# Load .env from backend root
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-4"

# In-memory cache for today
_cache: dict[str, tuple[int, str]] = {}

# File-based cache for past dates (permanent)
_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "narrations"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _load_file_cache(date_str: str) -> str | None:
    p = _CACHE_DIR / f"{date_str}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return None

def _save_file_cache(date_str: str, text: str) -> None:
    p = _CACHE_DIR / f"{date_str}.txt"
    p.write_text(text, encoding="utf-8")


def _time_period() -> str:
    """Return current time period for cache key."""
    from datetime import datetime
    h = datetime.now().hour
    if h < 6: return "night"
    if h < 12: return "morning"
    if h < 18: return "afternoon"
    return "evening"


def narrate_today(data: dict[str, Any]) -> str | None:
    """Send today's health data to LLM, get back a natural Thai narrative."""
    from datetime import date as date_cls
    target = data.get("date", "")
    score = data.get("readiness", 0)
    is_past = target != str(date_cls.today())

    # Past dates — use permanent file cache
    if is_past:
        cached = _load_file_cache(target)
        if cached:
            return cached

    # Today — use in-memory cache by period
    period = _time_period()
    cache_key = f"{target}_{period}"
    if not is_past and cache_key in _cache:
        cached_score, cached_text = _cache[cache_key]
        if cached_score == score:
            return cached_text

    signals = data.get("signals", {})
    strain = data.get("strain", {})
    recovery = data.get("recovery", {})

    # Build workout description with correct time period + Thai names
    WK_TH = {
        'TraditionalStrengthTraining': 'เวท', 'FunctionalStrengthTraining': 'Functional',
        'Elliptical': 'เครื่องเดิน', 'Cycling': 'ปั่นจักรยาน', 'Boxing': 'มวย',
        'CoreTraining': 'Core', 'HIIT': 'HIIT', 'CardioDance': 'เต้น',
        'Walking': 'เดิน', 'Running': 'วิ่ง', 'Yoga': 'โยคะ',
        'Swimming': 'ว่ายน้ำ', 'TableTennis': 'ปิงปอง',
    }
    workouts = strain.get('workouts', [])
    if workouts:
        wk_parts = []
        for w in workouts:
            name = WK_TH.get(w['type'], w['type'])
            t = w.get('time', '')
            h = int(t.split(':')[0]) if t and ':' in t else -1
            period_th = 'เช้า' if 6 <= h < 12 else 'บ่าย' if 12 <= h < 17 else 'เย็น' if 17 <= h < 21 else ''
            wk_parts.append(f"{name} ช่วง{period_th}" if period_th else name)
        wk_text = ', '.join(wk_parts)
    else:
        wk_text = ''

    # Build sleep description — no raw numbers
    sleep_hours = signals.get('sleep', {}).get('hours')
    if sleep_hours and sleep_hours > 0:
        if sleep_hours >= 7.5:
            sleep_text = "นอนเยอะ เต็มอิ่ม"
        elif sleep_hours >= 6.5:
            sleep_text = "นอนพอดี"
        elif sleep_hours >= 5:
            sleep_text = "นอนน้อยไปหน่อย"
        else:
            sleep_text = "นอนน้อยมาก"
        bedtime = signals.get('sleep', {}).get('bedtime', '')
        if bedtime:
            h = int(bedtime.split(':')[0])
            if h >= 1 and h <= 4:
                sleep_text += " และเข้านอนดึก"
    else:
        sleep_text = "NO_SLEEP_DATA"

    # Build data lines — semantic labels (short), let LLM compose freely
    data_lines = []

    # Readiness level (semantic label, not pre-written prose)
    readiness = data.get('readiness', 50)
    if readiness >= 70:
        readiness_label = "พร้อมเต็มที่"
    elif readiness >= 50:
        readiness_label = "ปกติ"
    elif readiness >= 35:
        readiness_label = "ยังไม่เต็มที่"
    else:
        readiness_label = "ล้ามาก"
    data_lines.append(f"ความพร้อมของร่างกาย: {readiness_label}")

    # Sleep
    if sleep_text != "NO_SLEEP_DATA":
        data_lines.append(f"การนอน: {sleep_text}")

    # Workouts
    if wk_text:
        data_lines.append(f"การออกกำลังกาย: {wk_text}")

    # Streak
    if signals.get('streak', 0) >= 3:
        data_lines.append("สถิติ: ยิมติดกันหลายวัน")

    # HRV/RHR — semantic status labels
    hrv_s = signals.get('hrv', {}).get('status', 'no_data')
    rhr_s = signals.get('rhr', {}).get('status', 'no_data')
    if hrv_s != 'no_data' and rhr_s != 'no_data':
        if hrv_s == 'good' and rhr_s == 'good':
            heart_label = "ฟื้นตัวดีมาก (หัวใจเต้นนิ่ง, ชีพจรต่ำ)"
        elif hrv_s == 'bad' and rhr_s == 'bad':
            heart_label = "ยังไม่ฟื้นตัว สัญญาณแย่ (หัวใจเต้นเร็วและไม่นิ่ง)"
        elif rhr_s == 'bad':
            heart_label = "ชีพจรสูงกว่าปกติมาก"
        elif hrv_s == 'bad':
            heart_label = "ความยืดหยุ่นของหัวใจต่ำกว่าปกติมาก"
        elif hrv_s == 'warning' or rhr_s == 'warning':
            heart_label = "สัญญาณชีพต่ำกว่าปกติเล็กน้อย"
        else:
            heart_label = "ปกติ"
        data_lines.append(f"หัวใจ: {heart_label}")
    elif hrv_s != 'no_data':
        if hrv_s == 'good':
            heart_label = "ความยืดหยุ่นของหัวใจดี"
        elif hrv_s == 'bad':
            heart_label = "ความยืดหยุ่นของหัวใจต่ำกว่าปกติมาก"
        elif hrv_s == 'warning':
            heart_label = "ความยืดหยุ่นของหัวใจต่ำเล็กน้อย"
        data_lines.append(f"หัวใจ: {heart_label}")

    # If only readiness line (no other data at all), use rotated fallback
    if len(data_lines) <= 1:
        import random
        FALLBACK_NORMAL = [
            "วันนี้สภาพโดยรวมปกติ ไม่มีสัญญาณผิดปกติ เป็นวันที่ข้อมูลจากอุปกรณ์มีไม่ครบ",
            "อยู่ในเกณฑ์ปกติ ข้อมูลจากนาฬิกาวันนี้จำกัด อาจไม่ได้ใส่ตลอดวัน",
            "ไม่มีสัญญาณน่ากังวลจากข้อมูลเท่าที่มี วันนี้อุปกรณ์เก็บข้อมูลได้น้อย",
            "สภาพโดยรวมไม่มีอะไรน่าเป็นห่วง เป็นวันที่ใส่นาฬิกาน้อยหรือไม่ได้ใส่",
        ]
        FALLBACK_LOW = [
            "พลังงานยังไม่เต็ม น่าจะกำลังปรับตัวจากวันก่อน ข้อมูลจากอุปกรณ์วันนี้ไม่ครบ",
            "ความพร้อมวันนี้น้อยกว่าปกติ อาจเป็นช่วงฟื้นตัว ข้อมูลอุปกรณ์มีจำกัด",
            "ยังไม่ค่อยพร้อมเต็มที่ เป็นวันที่อุปกรณ์เก็บข้อมูลได้ไม่มาก",
        ]
        pool = FALLBACK_NORMAL if readiness >= 50 else FALLBACK_LOW
        fallback = random.choice(pool)
        if is_past:
            _save_file_cache(target, fallback)
        return fallback

    # Build prompt — give LLM freedom to compose, keep guardrails strict
    prompt = f"""เขียนสรุปสุขภาพวันนี้เป็นภาษาไทย 1 ย่อหน้า (2–4 ประโยค) สั้นกระชับ อ่านลื่นเป็นธรรมชาติ

ข้อมูล:
{chr(10).join(f'- {s}' for s in data_lines)}

กฎเข้ม (ห้ามฝ่าฝืน):
1. **คำขึ้นต้นต้องหลากหลาย** — ผู้อ่านเห็นข้อความนี้วันละหลายรอบ ห้ามขึ้นต้นจำเจ อย่าเริ่มด้วย "ร่างกาย..." ทุกครั้ง ลองสลับเริ่มจากข้อมูลที่เด่นสุดของวัน (การนอน / การออกกำลังกาย / หัวใจ / ความรู้สึกโดยรวม) หรือใช้คำเปิดแบบอื่น เช่น "วันนี้...", "ช่วงเช้า...", "ตื่นมา...", "แม้...", "ถึงแม้..."
2. ห้ามใส่ตัวเลขหรือหน่วย (ms, bpm, ก้าว, ชั่วโมง)
3. ห้ามใช้คำว่า "เธอ"
4. **ห้ามแนะนำอะไรทั้งสิ้น** — ห้ามบอกว่าทำอะไรได้/ไม่ได้, ควร/ไม่ควร, เหมาะ/ไม่เหมาะ ห้ามใช้คำต่อไปนี้เด็ดขาด: "ควร", "ไม่ควร", "สามารถ...ได้", "ทำ...ได้ตามปกติ", "เหมาะแก่", "น่าจะ...ดี", "พัก", "นอน", "หยุด", "ลดความหนัก", "ระมัดระวัง", "ลองดู", "แนะนำ"
5. ห้ามเพิ่มข้อมูล อาการ หรือความรู้สึก ที่ไม่ได้อยู่ใน input
6. ห้ามจบด้วย filler เช่น "ถือว่าเป็นวันที่ดี", "ดูแลตัวเองนะ"
7. พูดครบทุก data point ที่ให้ แต่ไม่จำเป็นต้องเรียงตามลำดับ — เรียงใหม่ให้อ่านลื่น
8. **เขียนแค่ fact ล้วนๆ** — เหมือนรายงานสรุปสุขภาพ ไม่ใช่ที่ปรึกษา ไม่มีความเห็น ไม่มีคำแนะนำ"""

    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 250,
        "temperature": 0.9,
    }).encode("utf-8")

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_KEY}",
        },
    )

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            result = json.loads(resp.read())
            text = result["choices"][0]["message"]["content"].strip()
            if is_past:
                _save_file_cache(target, text)
            else:
                _cache[cache_key] = (score, text)
            return text
    except Exception as e:
        print(f"[narrator_llm] error: {e}")
        return None
