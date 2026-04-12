# smart_health

Whoop/Bevel-style recovery dashboard built on your Apple Watch data.

```
smart_health/
├── backend/          FastAPI + DuckDB (port 8400)
│   ├── app/
│   │   ├── parser.py    stream-parse export.xml → parquet
│   │   ├── queries.py   DuckDB daily aggregations
│   │   ├── recovery.py  Whoop-style recovery score
│   │   └── main.py      HTTP endpoints
│   └── data/
│       ├── raw/         original export.zip
│       └── parquet/     per-metric parquet files
└── frontend/         Next.js 14 dashboard (port 3400)
```

## 1. Export Apple Health data

On your iPhone:
1. Open **Health** app
2. Tap your profile picture (top-right)
3. Scroll down → **Export All Health Data**
4. AirDrop / send `export.zip` to this machine
5. Drop it at `backend/data/raw/export.zip`

The file is typically 200–800 MB and contains every HealthKit sample
your Watch has ever recorded.

## 2. Run the backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

# one-time ingest (or use the /ingest endpoint):
python -m app.parser data/raw/export.zip --out data/parquet

# start API
uvicorn app.main:app --host 0.0.0.0 --port 8400 --reload
```

Check it works: http://localhost:8400/status

Key endpoints:
- `GET /status` — which parquet files exist
- `GET /overview` — dashboard payload
- `GET /recovery?days=60` — daily recovery 0-100
- `GET /metrics/hrv?days=90` — daily HRV median
- `GET /metrics/sleep?days=30` — sleep stages per night
- `POST /ingest` — upload a new export.zip

## 3. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3400

## Recovery score

`backend/app/recovery.py` implements a Whoop-style 0-100 score:

| Component   | Weight | What it measures                              |
|-------------|--------|-----------------------------------------------|
| HRV         | 55%    | today vs your own rolling 30-day baseline     |
| Resting HR  | 25%    | today vs baseline (lower is better)           |
| Sleep       | 20%    | minutes asleep / 420 (7h target)              |

Each component is z-scored against a 30-day personal window, clipped at
±2σ, then mapped to 0-1. Needs ~2 weeks of prior data before scores
become meaningful (warmup period is filtered out automatically).

## Ports

- `8400` backend
- `3400` frontend

## Roadmap ideas

- Workout strain integral (HR above resting, Whoop-style scaling)
- Sleep-need model (strain → recommended sleep hours)
- Weekly / monthly trend digests
- iOS wrapper using HealthKit for live sync (Phase 2)
