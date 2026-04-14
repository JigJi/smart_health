"""FastAPI entrypoint for the smart_health backend.

Run:
    cd backend
    uvicorn app.main:app --host 0.0.0.0 --port 8400 --reload
"""
# reload trigger

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware

from .parser import parse_export
from .queries import HealthStore
from .recovery import compute_recovery_series
from .illness import detect_episodes
from .timeline import Timeline
from .zones import ZoneAnalyzer
from .admissions import detect_admissions_dict
from .pre_clinical import detect_drift_dict
from .unified_timeline import build_unified_timeline
from .daily_status import daily_status
from .journal import log_day, get_tags, get_entries, compute_insights
from .auto_insights import auto_insights
from .sync import receive_sync
from .smart_narrator import narrate_day
from .shortcut_sync import sync_from_shortcut
from .readiness import get_today


BASE = Path(__file__).resolve().parent.parent
RAW_DIR = BASE / "data" / "raw"
PARQUET_DIR = BASE / "data" / "parquet"
RAW_DIR.mkdir(parents=True, exist_ok=True)
PARQUET_DIR.mkdir(parents=True, exist_ok=True)


app = FastAPI(title="smart_health", version="0.1.0")

# Next.js dev server runs on 3400 (see README).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_user_dir(x_user_id: str | None = Header(default=None)) -> Path:
    user_id = (x_user_id or "default").strip() or "default"
    user_dir = PARQUET_DIR / "users" / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def get_store(user_dir: Path = Depends(get_user_dir)) -> HealthStore:
    return HealthStore(user_dir)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/status")
def status(user_dir: Path = Depends(get_user_dir)) -> dict[str, Any]:
    """List which parquet files exist + row counts — useful for 'am I ingested yet?'"""
    files: dict[str, int] = {}
    for p in sorted(user_dir.glob("*.parquet")):
        try:
            import duckdb
            n = duckdb.sql(f"SELECT count(*) FROM read_parquet('{p.as_posix()}')").fetchone()[0]
        except Exception:
            n = -1
        files[p.stem] = n
    return {"parquet_dir": str(user_dir), "files": files}


@app.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    user_dir: Path = Depends(get_user_dir),
) -> dict[str, Any]:
    """Upload an Apple Health export.zip (or export.xml) and reparse."""
    if not file.filename:
        raise HTTPException(400, "missing filename")

    dest = RAW_DIR / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    stats = parse_export(dest, user_dir)
    return {
        "received": file.filename,
        "size_mb": round(dest.stat().st_size / 1e6, 2),
        "records": stats.record_count,
        "sleep": stats.sleep_count,
        "workouts": stats.workout_count,
        "metrics_written": stats.metrics_written,
    }


@app.get("/metrics/hrv")
def metrics_hrv(days: int = 90, store: HealthStore = Depends(get_store)) -> list[dict[str, Any]]:
    return store.daily_hrv(days)


@app.get("/metrics/rhr")
def metrics_rhr(days: int = 90, store: HealthStore = Depends(get_store)) -> list[dict[str, Any]]:
    return store.daily_resting_hr(days)


@app.get("/metrics/sleep")
def metrics_sleep(days: int = 90, store: HealthStore = Depends(get_store)) -> list[dict[str, Any]]:
    return store.daily_sleep(days)


@app.get("/metrics/strain")
def metrics_strain(days: int = 90, store: HealthStore = Depends(get_store)) -> list[dict[str, Any]]:
    return store.daily_strain(days)


@app.get("/metrics/rings")
def metrics_rings(days: int = 90, store: HealthStore = Depends(get_store)) -> list[dict[str, Any]]:
    """Fitness app Activity rings (Move/Exercise/Stand) per day."""
    return store.daily_rings(days)


@app.get("/workouts")
def workouts(days: int = 90, store: HealthStore = Depends(get_store)) -> list[dict[str, Any]]:
    """Individual workout sessions with HR / distance / kcal."""
    return store.workouts(days)


@app.get("/recovery")
def recovery(days: int = 60, store: HealthStore = Depends(get_store)) -> list[dict[str, Any]]:
    return compute_recovery_series(store, days)


@app.get("/analytics/illness")
def analytics_illness(days: int = 365 * 6, store: HealthStore = Depends(get_store)) -> dict[str, Any]:
    return detect_episodes(store, days)


@app.get("/analytics/timeline")
def analytics_timeline(user_dir: Path = Depends(get_user_dir)) -> dict[str, Any]:
    tl = Timeline(user_dir)
    return {
        "monthly": tl.monthly(),
        "yearly": tl.yearly_summary(),
        "sports": tl.sport_breakdown(),
    }


@app.get("/analytics/admissions")
def analytics_admissions(user_dir: Path = Depends(get_user_dir)) -> list[dict[str, Any]]:
    return detect_admissions_dict(user_dir, min_gap_days=1, max_gap_days=14)


@app.get("/analytics/drift")
def analytics_drift(user_dir: Path = Depends(get_user_dir)) -> list[dict[str, Any]]:
    return detect_drift_dict(user_dir)


@app.get("/analytics/timeline_unified")
def analytics_timeline_unified(user_dir: Path = Depends(get_user_dir)) -> list[dict[str, Any]]:
    return build_unified_timeline(user_dir)


@app.get("/daily_status")
def daily_status_endpoint(days: int = 35, user_dir: Path = Depends(get_user_dir)) -> dict[str, Any]:
    return daily_status(user_dir, days)


@app.get("/analytics/zones")
def analytics_zones(days: int = 365 * 6, user_dir: Path = Depends(get_user_dir)) -> dict[str, Any]:
    za = ZoneAnalyzer(user_dir)
    return {
        "max_hr": za.estimate_max_hr(),
        "by_sport": za.zones_by_sport(days),
        "polarization_365d": za.polarization_index(365),
        "recent_workouts": za.recent_workouts_with_zones(20),
    }


@app.get("/journal/tags")
def journal_tags() -> list[dict[str, Any]]:
    return get_tags()


@app.post("/journal")
def journal_log(body: dict[str, Any]) -> dict[str, Any]:
    day = body.get("day", str(date.today()))
    tags = body.get("tags", [])
    note = body.get("note", "")
    return log_day(day, tags, note)


@app.get("/journal/entries")
def journal_entries(days: int = 90) -> list[dict[str, Any]]:
    return get_entries(days)


@app.get("/journal/insights")
def journal_insights(user_dir: Path = Depends(get_user_dir)) -> list[dict[str, Any]]:
    return compute_insights(user_dir)


@app.get("/insights/auto")
def auto_insights_endpoint(user_dir: Path = Depends(get_user_dir)) -> list[dict[str, Any]]:
    return auto_insights(user_dir)


@app.post("/sync")
def sync_data(body: dict[str, Any], user_dir: Path = Depends(get_user_dir)) -> dict[str, Any]:
    """Receive incremental health data from Shortcuts / auto-export app."""
    counts = receive_sync(user_dir, body)
    return {"status": "ok", "rows_added": counts}


@app.post("/sync/shortcut")
async def sync_shortcut(
    request: Request,
    user_dir: Path = Depends(get_user_dir),
    x_user_id: str | None = Header(default=None),
) -> dict[str, Any]:
    """Receive plain-text pipe-delimited data from Apple Shortcuts.
    Much easier to build in Shortcuts than JSON."""
    body = await request.body()
    text = body.decode("utf-8")
    user_id = (x_user_id or "default").strip() or "default"
    return sync_from_shortcut(user_dir, text, user_id)


@app.get("/narrate")
def narrate(day: str | None = None, user_dir: Path = Depends(get_user_dir)) -> dict[str, Any]:
    """Personalized daily assessment from smart narrator."""
    return narrate_day(user_dir, day)


@app.get("/today")
def today_endpoint(date: str | None = None, user_dir: Path = Depends(get_user_dir)) -> dict[str, Any]:
    """Unified daily dashboard — readiness, strain, recovery, sleep, tip."""
    return get_today(user_dir, target_date=date)


@app.get("/calendar")
def calendar_endpoint(
    year: int | None = None,
    month: int | None = None,
    user_dir: Path = Depends(get_user_dir),
) -> dict[str, Any]:
    """Score summary for calendar view — one month at a time."""
    from .readiness import get_calendar_month
    from datetime import date
    y = year or date.today().year
    m = month or date.today().month
    return get_calendar_month(user_dir, y, m)


@app.get("/overview")
def overview(store: HealthStore = Depends(get_store)) -> dict[str, Any]:
    """One-shot dashboard payload: latest recovery + snapshot + 30d series."""
    series = compute_recovery_series(store, 30)
    latest = series[-1] if series else None
    return {
        "latest": latest,
        "snapshot": store.latest_snapshot(),
        "recovery_30d": series,
    }
