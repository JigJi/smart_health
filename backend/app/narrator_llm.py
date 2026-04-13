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
MODEL = "google/gemini-2.0-flash-lite-001"

# Simple cache: (date, score) → narration
_cache: dict[str, tuple[int, str]] = {}  # date → (score, text)


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
    today = data.get("date", "")
    score = data.get("readiness", 0)
    period = _time_period()
    cache_key = f"{today}_{period}"

    # Return cache if same day + period + score hasn't changed
    if cache_key in _cache:
        cached_score, cached_text = _cache[cache_key]
        if cached_score == score:
            return cached_text

    signals = data.get("signals", {})
    strain = data.get("strain", {})
    recovery = data.get("recovery", {})

    prompt = f"""เขียนสรุปสุขภาพวันนี้ 3-4 ประโยค ภาษาไทย ย่อหน้าเดียว ห้ามสั้นกว่า 3 ประโยค

สไตล์:
- เหมือนโค้ชส่วนตัวที่รู้จักคุณดี พูดตรงๆ แต่ไม่ดราม่า
- เล่าข้อเท็จจริงที่เกิดขึ้น ไม่ตัดสิน ไม่น่ากลัว
- ถ้าออกกำลังกายไปแล้ว ให้พูดถึงสิ่งที่ทำไปแล้วเท่านั้น
- ห้ามแนะนำให้ออกกำลังกาย ห้ามเชียร์ ห้ามบอกว่า "ลองไป" "น่าจะ" "ควรจะ" "ถ้าได้...จะดี"
- ห้ามให้คำแนะนำใดๆ ทั้งสิ้น ไม่ว่าจะเป็นการออกกำลังกาย การนอน การกิน
- แค่เล่าว่าร่างกายเป็นยังไงตอนนี้ จบ
- ห้ามใช้คำว่า "ทรุด" "ดึงดัน" "อันตราย" "แบตเตอรี่" หรือคำดราม่า
- ห้ามใช้ "เธอ" ใช้ "คุณ" หรือไม่มีสรรพนาม
- ไม่ใส่ emoji ไม่ขึ้นหัวข้อ
- ห้ามพูดถึงคะแนน เปอร์เซ็นต์ หรือตัวเลข HRV/RHR

ตัวอย่างโทนที่ต้องการ:
- "เช้านี้ลุกมาเล่นเวทกับเดินทั้งที่นอนดึก ร่างกายยังตอบสนองได้ดีอยู่แม้พักผ่อนมาน้อย ถือว่าวันนี้ได้ใช้ร่างกายไปเต็มที่แล้ว"
- "วันนี้ทุกอย่างเข้าที่ หัวใจเต้นนิ่งกว่าปกติ นอนมาเต็มอิ่ม ร่างกายพร้อมเต็มที่"

ข้อมูลวันนี้:
- คะแนนความพร้อม: {data.get('readiness')}/100 ({data.get('readiness_label')})
- HRV: {signals.get('hrv', {}).get('value')} ms (ปกติ {signals.get('hrv', {}).get('baseline')} ms)
- RHR: {signals.get('rhr', {}).get('value')} bpm (ปกติ {signals.get('rhr', {}).get('baseline')} bpm)
- นอน: {signals.get('sleep', {}).get('hours')} ชม. เข้านอน {signals.get('sleep', {}).get('bedtime')} ตื่น {signals.get('sleep', {}).get('wakeup')}
- เดินเมื่อวาน: {signals.get('prev_steps', {}).get('value')} ก้าว
- ยิมติดกัน: {signals.get('streak')} วัน
- ออกกำลังกายวันนี้: {len(strain.get('workouts', []))} ครั้ง ({', '.join(w['type'] for w in strain.get('workouts', []))})
- Recovery: {recovery.get('score')}%
- วัน: {data.get('day_th')}
- เวลาปัจจุบัน: {__import__('datetime').datetime.now().strftime('%H:%M')}
- ช่วง: {_time_period()}"""

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
            _cache[cache_key] = (score, text)
            return text
    except Exception as e:
        print(f"[narrator_llm] error: {e}")
        return None
