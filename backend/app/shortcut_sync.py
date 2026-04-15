"""Shortcut-friendly sync endpoint.

Apple Shortcuts' "Find Health Samples" returns data in a specific
format. This endpoint accepts that format directly — no complex JSON
building needed in the Shortcut.

The Shortcut sends plain text lines (easiest to build in Shortcuts):
  HR|2026-04-12T09:00:00+0700|72
  HR|2026-04-12T09:05:00+0700|75
  HRV|2026-04-12T06:00:00+0700|35.5
  RHR|2026-04-12T08:00:00+0700|63
  WK|TraditionalStrengthTraining|2026-04-12T17:00:00+0700|55|120|155|320
  STEPS|2026-04-12T12:00:00+0700|5432

This is trivially easy to build in Shortcuts using "Combine Text".
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .sync import receive_sync


def parse_shortcut_text(text: str) -> dict[str, Any]:
    """Parse the simple pipe-delimited format from Shortcuts into
    the standard sync payload format."""
    payload: dict[str, list] = {
        "heart_rate": [],
        "hrv": [],
        "resting_heart_rate": [],
        "workouts": [],
        "steps": [],
        "active_energy": [],
        "spo2": [],
        "respiratory_rate": [],
        "sleep": [],
    }

    for line in text.strip().split("\n"):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue

        kind = parts[0].upper()

        if kind == "HR" and len(parts) >= 3:
            payload["heart_rate"].append({
                "time": parts[1], "value": float(parts[2])
            })
        elif kind == "HRV" and len(parts) >= 3:
            payload["hrv"].append({
                "time": parts[1], "value": float(parts[2])
            })
        elif kind == "RHR" and len(parts) >= 3:
            payload["resting_heart_rate"].append({
                "time": parts[1], "value": float(parts[2])
            })
        elif kind == "WK" and len(parts) >= 4:
            workout = {
                "type": parts[1],
                "start": parts[2],
                "duration_min": float(parts[3]) if parts[3] else 0,
            }
            if len(parts) > 4 and parts[4]:
                workout["hr_avg"] = float(parts[4])
            if len(parts) > 5 and parts[5]:
                workout["hr_max"] = float(parts[5])
            if len(parts) > 6 and parts[6]:
                workout["active_kcal"] = float(parts[6])
            payload["workouts"].append(workout)
        elif kind == "STEPS" and len(parts) >= 3:
            payload["steps"].append({
                "time": parts[1], "value": float(parts[2])
            })
        elif kind == "CAL" and len(parts) >= 3:
            payload["active_energy"].append({
                "time": parts[1], "value": float(parts[2])
            })
        elif kind == "SPO2" and len(parts) >= 3:
            # iOS sends percent as 0-1 (e.g. 0.97) — keep raw fractional form
            payload["spo2"].append({
                "time": parts[1], "value": float(parts[2])
            })
        elif kind == "RR" and len(parts) >= 3:
            payload["respiratory_rate"].append({
                "time": parts[1], "value": float(parts[2])
            })
        elif kind == "SLEEP" and len(parts) >= 4:
            payload["sleep"].append({
                "start": parts[1],
                "end": parts[2],
                "stage": parts[3],
            })

    # Remove empty lists
    return {k: v for k, v in payload.items() if v}


def sync_from_shortcut(user_dir: str | Path, text: str, user_id: str = "default") -> dict[str, Any]:
    """Parse shortcut text and sync to the caller-resolved per-user parquet dir."""
    user_dir = Path(user_dir)
    user_dir.mkdir(parents=True, exist_ok=True)
    payload = parse_shortcut_text(text)
    counts = receive_sync(user_dir, payload)
    total = sum(counts.values())
    return {
        "status": "ok",
        "user_id": user_id,
        "rows_added": counts,
        "total": total,
        "message_th": f"Sync สำเร็จ! รับข้อมูล {total} รายการ",
    }
