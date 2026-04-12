# 🔄 Handoff — Windows → Mac

## สิ่งที่ทำเสร็จแล้ว (Windows)

### Backend (Python/FastAPI) ✅ ทำงานได้เลย
```
backend/
├── app/
│   ├── parser.py            ← parse export.zip → parquet (stream, 1.66M records ผ่าน)
│   ├── queries.py           ← DuckDB daily aggregations
│   ├── recovery.py          ← Whoop-style recovery score
│   ├── illness.py           ← anomaly detector (4/4 validated: Dengue, LASIK, Flu A, Flu B)
│   ├── admissions.py        ← hospital admission detector (gap-based, 3/3 matched)
│   ├── pre_clinical.py      ← HRV drift early-warning (caught Sep 16 admit 8d early)
│   ├── unified_timeline.py  ← master event stream (193 events, 5 years)
│   ├── timeline.py          ← multi-year fitness trends
│   ├── zones.py             ← HR zone analysis (max HR 198 bpm)
│   ├── daily_status.py      ← per-day normal/warning/bad + Thai reasons
│   ├── daily_assessment.py  ← 12-state emoji assessment (⚡😊💪😤😴🤒...)
│   ├── auto_insights.py     ← zero-input Whoop-style correlations (6 insights)
│   ├── personal_profile.py  ← learns YOUR patterns from 5yr data
│   ├── smart_narrator.py    ← personalized Thai-language daily assessment
│   ├── journal.py           ← behavior logging + correlation
│   ├── sync.py              ← receive incremental data (JSON)
│   ├── shortcut_sync.py     ← receive pipe-delimited text from Shortcuts/iOS app
│   └── main.py              ← FastAPI endpoints (25+ routes)
├── data/
│   ├── raw/export.zip       ← user's Apple Health export (41MB)
│   └── parquet/             ← 15 parquet files, parsed from export
└── requirements.txt
```

### Frontend (Next.js) ✅ ทำงานได้เลย
```
frontend/
├── app/
│   ├── page.tsx             ← summary-first dashboard (TodayCard + WeekStrip + MonthHeatmap)
│   └── journal/page.tsx     ← behavior logging page
├── components/
│   ├── TodayCard.tsx        ← big status card with emoji + Thai reasons
│   ├── DayStrip.tsx         ← 7-day colored strip
│   ├── MonthHeatmap.tsx     ← 30-day calendar heatmap
│   ├── NormsCard.tsx        ← "your normal HRV/RHR" card
│   ├── UnifiedTimeline.tsx  ← 5-year SVG timeline
│   ├── ZoneBar.tsx          ← HR zone stacked bars
│   ├── YearlyCards.tsx      ← year-over-year training summary
│   ├── PolarizationCard.tsx ← 80/20 training polarization
│   ├── TrendChart.tsx       ← Recharts line chart wrapper
│   └── RecoveryRing.tsx     ← circular progress ring
└── lib/api.ts               ← typed API client
```

### iOS App (Swift) ✅ code เสร็จ พร้อม build บน Mac
```
ios_app/HealthSync/
├── HealthSyncApp.swift      ← app entry point
├── ContentView.swift        ← minimal UI (status + sync button)
├── HealthKitManager.swift   ← HealthKit auth + background delivery + sync
└── APIClient.swift          ← POST to backend
```

## Ports
- **8401** — Backend FastAPI (8400 zombie, ใช้ 8401 แทน)
- **3400** — Frontend Next.js

## User's Personal Data Highlights
- **5 years** of Apple Watch data (Jan 2021 → Apr 2026)
- HRV baseline: **37 ms** (range 27-49)
- RHR baseline: **65 bpm**
- Max HR: **198 bpm**
- Sweet spot: **5 sessions/week** → best next-week HRV
- Best day: **Friday** (HRV 38.2) / Worst: **Saturday** (33.6)
- Best month: **March** / Worst: **August**
- Recovery from Strength: **1 day**
- Moderate trap: **29% Z3** (should be <5%)
- 3 confirmed hospital admissions detected ✅
- 6 confirmed real-world events validated ✅

## วิธีรันบน Windows (ถ้ากลับมา)
```bash
# Backend
cd backend
.venv\Scripts\activate
uvicorn app.main:app --port 8401 --reload

# Frontend
cd frontend
npm run dev
```

## ⚙️ สิ่งที่ต้องทำบน Mac

### Step 1: Clone / Copy project
```bash
# ถ้าใช้ git remote (GitHub/GitLab)
git clone <repo-url>

# หรือ copy ผ่าน Tailscale / USB / cloud
```

### Step 2: สร้าง Xcode Project
1. เปิด **Xcode** → File → New → Project
2. เลือก **App** (iOS)
3. ตั้งชื่อ: `HealthSync`
4. Team: เลือก Apple Developer account ของคุณ
5. Bundle ID: `com.yourname.healthsync`
6. Interface: **SwiftUI**
7. Language: **Swift**
8. เลือก folder `ios_app/` เป็น location

### Step 3: เพิ่ม HealthKit Capability
1. เลือก project ใน navigator → target HealthSync
2. Tab **Signing & Capabilities**
3. กด **+ Capability** → เลือก **HealthKit**
4. ติ๊ก: ☑ Clinical Health Records (ไม่จำเป็น) ☑ Background Delivery ✅

### Step 4: เพิ่ม Background Modes
1. กด **+ Capability** → **Background Modes**
2. ติ๊ก: ☑ Background fetch ☑ Background processing

### Step 5: แก้ Info.plist
เพิ่ม keys เหล่านี้ (Xcode จะสร้างให้ถ้าเพิ่ม HealthKit capability):
```
NSHealthShareUsageDescription = "เพื่อวิเคราะห์สุขภาพและส่งสรุปรายวันให้คุณ"
NSHealthUpdateUsageDescription = "ไม่ได้เขียนข้อมูล แค่อ่านเท่านั้น"
```

### Step 6: Copy Swift files
ลาก 4 ไฟล์จาก `ios_app/HealthSync/` เข้า Xcode project:
- `HealthSyncApp.swift`
- `ContentView.swift`
- `HealthKitManager.swift`
- `APIClient.swift`

(ลบไฟล์ default ที่ Xcode สร้างให้ เช่น ContentView.swift เดิม)

### Step 7: แก้ API URL
ใน `APIClient.swift` แก้:
```swift
static let baseURL = "http://YOUR_TAILSCALE_IP:8401"
```
ใช้ Tailscale IP ของ Windows server (100.105.182.33)

### Step 8: Build & Run
1. เลือก iPhone ของคุณจาก device dropdown
2. กด **⌘R** (Run)
3. iPhone จะถามอนุญาต Health → กด Allow
4. App จะ sync ครั้งแรก → ดู backend log ว่าได้รับ data

### Step 9: TestFlight (optional สำหรับแจกเพื่อน)
1. Product → Archive
2. Distribute → TestFlight
3. เพิ่ม email เพื่อนเป็น tester
4. เพื่อนโหลดจาก TestFlight app

## Architecture สรุป
```
┌──────────┐    ┌──────────┐    ┌──────────┐
│  iPhone  │    │  Backend │    │  LINE OA │
│          │    │  (FastAPI)│    │  (Phase2)│
│ HealthKit│    │          │    │          │
│    ↓     │    │ Profile  │    │ Chat     │
│ App ท่อ  │───→│ Narrator │───→│ Push     │
│ (Swift)  │    │ Insights │    │ Summary  │
│          │    │          │    │          │
└──────────┘    └──────────┘    └──────────┘
  sync 24/7      runs 24/7       Phase 2
```

## Next Steps (เรียงลำดับ)
1. ✅ Build iOS app บน Mac → test กับ iPhone ของตัวเอง
2. LINE OA webhook (ต้อง LINE Developer credentials)
3. Deploy backend to cloud (Railway/DigitalOcean)
4. TestFlight ให้เพื่อน 5-10 คนลอง
5. App Store submission (ถ้า validate ผ่าน)
