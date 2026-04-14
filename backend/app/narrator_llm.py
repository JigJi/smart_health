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

    # Build data lines — only facts, no day-of-week
    data_lines = []

    # Readiness level
    readiness = data.get('readiness', 50)
    if readiness >= 70:
        data_lines.append("- ร่างกายพร้อมเต็มที่")
    elif readiness >= 50:
        data_lines.append("- ร่างกายอยู่ในเกณฑ์ปกติ")
    elif readiness >= 35:
        data_lines.append("- ร่างกายยังไม่ค่อยพร้อม")
    else:
        data_lines.append("- ร่างกายล้ามาก")

    # Sleep
    if sleep_text != "NO_SLEEP_DATA":
        data_lines.append(f"- {sleep_text}")

    # Workouts
    if wk_text:
        data_lines.append(f"- ออกกำลังกาย: {wk_text}")

    # Streak
    if signals.get('streak', 0) >= 3:
        data_lines.append("- ยิมติดกันมาหลายวัน")

    # HRV/RHR — be specific about each
    hrv_s = signals.get('hrv', {}).get('status', 'no_data')
    rhr_s = signals.get('rhr', {}).get('status', 'no_data')
    if hrv_s != 'no_data' and rhr_s != 'no_data':
        if hrv_s == 'good' and rhr_s == 'good':
            data_lines.append("- หัวใจเต้นนิ่งกว่าปกติ ร่างกายฟื้นตัวดี")
        elif hrv_s == 'bad' and rhr_s == 'bad':
            data_lines.append("- หัวใจเต้นเร็วกว่าปกติมาก ร่างกายยังไม่ฟื้นตัว สัญญาณไม่ดี")
        elif rhr_s == 'bad':
            data_lines.append("- หัวใจเต้นเร็วกว่าปกติมาก")
        elif hrv_s == 'bad':
            data_lines.append("- ความยืดหยุ่นของหัวใจต่ำกว่าปกติมาก")
        elif hrv_s == 'warning' or rhr_s == 'warning':
            data_lines.append("- สัญญาณชีพต่ำกว่าปกติเล็กน้อย")
        else:
            data_lines.append("- การทำงานของหัวใจปกติดี")
    elif hrv_s != 'no_data':
        if hrv_s == 'good':
            data_lines.append("- ความยืดหยุ่นของหัวใจดี")
        elif hrv_s == 'bad':
            data_lines.append("- ความยืดหยุ่นของหัวใจต่ำกว่าปกติมาก")
        elif hrv_s == 'warning':
            data_lines.append("- ความยืดหยุ่นของหัวใจต่ำกว่าปกติเล็กน้อย")

    data_block = '\n'.join(data_lines)

    # If only readiness line (no other data at all), use template
    if len(data_lines) <= 1:
        if readiness >= 50:
            fallback = "ร่างกายอยู่ในเกณฑ์ปกติ ไม่มีสัญญาณผิดปกติ วันนี้ไม่ได้ใส่นาฬิกาหรือไม่มีข้อมูลจากอุปกรณ์"
        else:
            fallback = "ร่างกายยังไม่ค่อยพร้อม อาจเป็นช่วงที่กำลังปรับตัวหรือฟื้นตัวจากกิจกรรมก่อนหน้า วันนี้ไม่มีข้อมูลจากอุปกรณ์มากนัก"
        if is_past:
            _save_file_cache(target, fallback)
        return fallback

    # Build structured prompt — one sentence per data point
    sentences = []
    for line in data_lines:
        sentences.append(line.lstrip('- '))

    prompt = f"""แปลงข้อมูลสุขภาพด้านล่างเป็นข้อความภาษาไทย ย่อหน้าเดียว เขียนให้ลื่นเป็นธรรมชาติ

กฎ:
- ข้อมูลแต่ละข้อ = 1 ประโยค ห้ามซ้ำความ ห้ามขยายเกินข้อมูลที่ให้
- เชื่อมประโยคให้อ่านลื่น ไม่ใช่แค่แปลทีละบรรทัด
- ห้ามใส่ตัวเลข ห้ามให้คำแนะนำ ห้ามใช้ "เธอ"
- ห้ามเพิ่มข้อมูลที่ไม่ได้ให้ ห้ามเพิ่มอาการ ห้ามเพิ่มความรู้สึก
- ห้ามจบด้วย filler เช่น "ถือว่าเป็นวันที่ดี"

ข้อมูล:
{chr(10).join(f'{i+1}. {s}' for i, s in enumerate(sentences))}"""

    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 250,
        "temperature": 0.7,
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
