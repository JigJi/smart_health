# 🔄 Handoff — Mac → Windows Server

> **สำหรับ Claude session ใหม่บน Windows server**: อ่านจนจบก่อนทำอะไร Jig เป็น dev สาย web/backend/AI ไทย กำลังทำ iOS app แรกในชีวิต ตอบภาษาไทยเสมอ เป้าหมายของ session นี้คือ **deploy backend + frontend บน Windows server** ให้ iOS TestFlight user ต่อได้จากทุกที่

---

## Context ย่อ

Smart_health = แพลตฟอร์มวิเคราะห์สุขภาพจาก Apple Watch ทำ 3 ส่วน:

| Component | Tech | Dev port | Prod runs on |
|-----------|------|----------|--------------|
| Backend | FastAPI + DuckDB + parquet | 8401 | **Windows server (เครื่องนี้)** |
| Frontend | Next.js 14 | 3400 | **Windows server** |
| iOS app | Swift + WKWebView | — | iPhone via TestFlight |

iOS เป็น native shell wrap WebView ที่ชี้ไป Next.js dashboard + เพิ่ม native (HealthKit sync, onboarding, SyncBanner) **iOS dev ต้องอยู่ Mac เสมอ** — Apple บังคับ

---

## Jig's preferences (สำคัญมาก — อย่าเดา)

- **ตอบภาษาไทยเสมอ** ยกเว้นบอกให้ตอบอังกฤษ
- **Universal ไม่ bias** — ห้ามปรับ threshold ให้ Jig ดูดี ต้อง follow clinical standard (Whoop/Oura/Bevel) เสมอ
- **ไม่แนะนำใน narration** — ห้าม "ควร", "พัก", "สามารถ...ได้" etc. แสดง fact ล้วนๆ
- **HealthKit readTypes ขอครบทีเดียว** ห้ามเพิ่มทีละนิด
- **LLM narration ใช้ semantic label** ไม่ hardcode Thai sentence
- **WebView + Next.js** ไม่ native SwiftUI — iOS/Android จะใช้ UI เดียวกัน

Memory เต็ม ไม่ได้ transfer มา — session ใหม่นี้จะต้องสร้างของตัวเอง

---

## งานที่เพิ่งทำเสร็จใน session Mac (วันนี้ 2026-04-14)

### ✅ เสร็จสมบูรณ์
- **HealthKit sync end-to-end** — HR, HRV, RHR, Steps, SpO2, RR, Sleep, Workouts, Active Energy ไหลจาก Apple Watch → iOS → backend parquet
- **iOS polish**: Onboarding (ขาว แบบ Bevel → ดำ dashboard), SyncBanner % progress, scenePhase auto-sync, silent WebView refetch (ไม่โหลดใหม่แล้ว)
- **30+ HealthKit types ใน readTypes** — ขอครั้งเดียว ไม่ prompt ซ้ำ
- **Narrator**: semantic label + temp 0.9 + rules กันคำแนะนำ
- **HRV clinical**: เปลี่ยนจาก median ทั้งวัน → `avg` overnight (`hour < 10`) ตาม clinical standard
- **SpO2/RR**: จาก latest → avg
- **Readiness penalty consistency**: penalty apply ทุกวัน (ไม่ใช่แค่ today) — ประวัติคงที่
- **Calendar ↔ dashboard match**: สีตรงกันทุกวัน
- **Tap-delay fix**: viewport user-scalable=no + touch-action: manipulation

### 🟡 Partial — **เริ่มทำแต่ยังไม่เสร็จ** ⚠️ ต้อง finish ก่อน deploy
**Phase 1: Multi-user backend** — เสร็จ 1/6 task

- ✅ `backend/app/shortcut_sync.py` — write ไป `data/parquet/users/{user_id}/` แล้ว
- ❌ `backend/app/main.py` — endpoints อื่นยังใช้ `PARQUET_DIR` ตรงๆ (single-user) **งานหลักที่ต้องทำ**
- ❌ Data migration: parquet ยังอยู่ root `data/parquet/*.parquet` ต้องย้ายไป `data/parquet/users/default/`
- ❌ iOS `APIClient.swift`: ส่ง `X-User-Id: "default"` hardcoded → ต้องเปลี่ยนเป็น UUID per install
- ❌ Frontend: ยังไม่รับ `?uid=X` query param
- ❌ Test fake user

---

## Phase plan (ลำดับงาน)

### Phase 1: finish multi-user backend (เริ่มจากตรงนี้!)

1. **`backend/app/main.py`** — ใช้ FastAPI `Depends`:
   ```python
   from fastapi import Depends, Header
   # (import แล้วใน main.py จากรอบก่อน)

   def get_user_dir(x_user_id: str | None = Header(default="default")) -> Path:
       user_id = x_user_id or "default"
       user_dir = PARQUET_DIR / "users" / user_id
       user_dir.mkdir(parents=True, exist_ok=True)
       return user_dir

   def get_store(user_dir: Path = Depends(get_user_dir)) -> HealthStore:
       return HealthStore(user_dir)
   ```
   ทุก endpoint เปลี่ยนเป็น `user_dir: Path = Depends(get_user_dir)` แล้ว pass ไปยัง module functions (ซึ่งส่วนใหญ่รับ `parquet_dir` เป็น arg อยู่แล้ว)

2. **Migration script** `backend/scripts/migrate_to_multiuser.py`:
   ```python
   # ย้าย backend/data/parquet/*.parquet → backend/data/parquet/users/default/
   # (เฉพาะไฟล์ *.parquet ไม่ย้าย users/ subdirectory)
   ```

3. **iOS `APIClient.swift`**:
   ```swift
   static func userId() -> String {
       if let id = UserDefaults.standard.string(forKey: "userId") { return id }
       let new = UUID().uuidString
       UserDefaults.standard.set(new, forKey: "userId")
       return new
   }
   ```
   ส่งใน `X-User-Id` header ของ postSync + ส่งใน URL query param `?uid=XXX` ของ WebView (เพื่อ frontend forward ให้ backend)

4. **Frontend** `app/api/today/route.ts` + `calendar/route.ts`: อ่าน `?uid` query → forward เป็น `X-User-Id` header ไป backend

5. **Test**: POST ด้วย `X-User-Id: "test-friend"` → verify ได้ folder `users/test-friend/` แยกจาก Jig

### Phase 2: Deploy บน Windows server (งานหลักของ session นี้)

1. **Repo cleanup**:
   - บน Windows มี folder `smart_watch` เก่า — rename เป็น `smart_watch_OLD_backup`
   - `git clone https://github.com/JigJi/smart_health.git`

2. **Dependencies**:
   - Python 3.12 (https://python.org/downloads) — ติ๊ก "Add to PATH"
   - Node.js 20 LTS (https://nodejs.org)
   - `cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt`
     (ถ้า requirements.txt ไม่มี — สร้างจาก imports ในไฟล์ `.py`)
   - `cd frontend && npm install && npm run build`

3. **Data migration**: Windows มี parquet เก่า ไม่ใช่ที่ Jig ใช้ล่าสุด (2 options):
   - **(a)** Let iOS rebuild — เริ่ม cold ~1 สัปดาห์ baseline
   - **(b) แนะนำ**: Transfer parquet จาก Mac (~1.2GB) ผ่าน Google Drive / Tailscale file share → run migration script ให้เข้า `users/default/`

4. **Windows Service** (ใช้ NSSM — https://nssm.cc/download):
   ```
   nssm install smart_health_backend "C:\Python312\python.exe" "-m uvicorn app.main:app --host 0.0.0.0 --port 8401"
   (set working dir = smart_health/backend)

   nssm install smart_health_frontend "C:\Program Files\nodejs\npm.cmd" "start"
   (set working dir = smart_health/frontend, หลัง npm run build)

   nssm start smart_health_backend
   nssm start smart_health_frontend
   ```

5. **Public HTTPS** (ต้องใช้ iOS ATS):
   - Install cloudflared — https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
   - Quick tunnel (ephemeral, 20 นาที):
     ```
     cloudflared tunnel --url http://localhost:3400
     ```
     จะได้ `https://xxx.trycloudflare.com`
   - ดีกว่า: named tunnel ผูกกับ Jig's domain (ถ้ามี) → URL ถาวร

6. **Update iOS URLs** (Jig ทำบน Mac):
   - `ios_app/HealthSync/APIClient.swift:13` → tunnel URL
   - `ios_app/HealthSync/ContentView.swift:14` → tunnel URL
   - Push → Jig pull บน Mac → rebuild iOS

### Phase 3: TestFlight (Mac เท่านั้น — รอ Apple approve)
Jig สมัคร Apple Developer แล้ว (฿3,590/ปี) วันนี้ 14 เม.ย. — รอ 24-48 ชม. approve

---

## Env / running notes

- Mac path: `/Users/jirawatsang/Desktop/Jig_Project/0_dev/smart_health`
- Git: `origin https://github.com/JigJi/smart_health.git`
- **Dev**: uvicorn ใช้ `--reload` (auto-pick up Python edits)
- **Prod**: `--reload` ต้องเอาออก (Windows Service)
- Frontend dev: `npm run dev -p 3400 -H 0.0.0.0`
- Frontend prod: `npm run build && npm start -p 3400`
- Backend .env: `OPENROUTER_API_KEY=...` (driving LLM narrator) — **gitignore ไม่อยู่ใน repo** ต้องขอจาก Jig แล้ว copy ไป Windows เอง

## Ports
- **8401** Backend (avoid 8400 = zombie)
- **3400** Frontend

## Gotchas

- **SourceKit ใน Xcode แจ้ง false errors** ("Cannot find type...") — ไม่จริง build OK
- **HRV baseline `hour < 10`** — อย่าเปลี่ยนกลับไปใช้ all-day ถือเป็น clinical standard
- **Readiness penalty apply ทุกวัน** (ไม่ใช่แค่ today) — ตั้งใจ ไม่ใช่ bug "วันนั้นของวันนั้น" ประวัติคงที่
- **iOS readTypes 30+ types** — อย่าลบ ถ้าลบ user ต้อง re-grant permission ทั้งยวง

---

## Storage / DB strategy

**ไม่ต้องใช้ DB server** — ใช้ parquet-per-user (DuckDB query เร็วกว่า PostgreSQL สำหรับ health analytics):

```
data/parquet/users/
├── default/              ← Jig's data
├── {uuid-friend-1}/
└── {uuid-friend-2}/
```

Scale estimate:
- 1 user (with 5yr history) ≈ 1.2GB
- 10 friends (cold start) ≈ 3-5GB
- 100 users ≈ 30-50GB

Windows server มี disk space เยอะ = approach นี้เหมาะ

**เมื่อไรควรพิจารณาเพิ่ม SQLite:**
- ต้องการ auth / user profiles / emails
- Journal entries + tags
- Daily notes

**เมื่อไรควรย้ายไป PostgreSQL:**
- Users > 1,000
- Multi-server / load balancing
- Replication + backup automation

สำหรับ MVP ตอนนี้ (Jig + friends ≤ 10) ไม่ต้อง DB เพิ่มเลย

## Future: data retention policy (when scale > 50 users)

ปัจจุบันเก็บ raw samples ทุกอันทุกวัน — 80-90% ไม่ได้ใช้จริง (ใช้แค่ daily aggregate สำหรับ trend + 60-90 วันล่าสุดสำหรับ baseline)

**Recommended hybrid strategy (future work):**
- Raw samples: เก็บแค่ last 365 days
- Daily aggregates (pre-computed: HRV_daily, RHR_daily, sleep_hours, steps_total, ...): เก็บตลอดชีพ (1 row/day = 2MB/user for 5 years)
- Background job รัน daily → aggregate → delete raw > 1 year

**ประโยชน์:**
- Disk usage ลด 85-90%
- Dashboard/calendar/trend ทำงานเหมือนเดิม (ใช้ aggregate)
- Privacy friendly (raw HR ของปีที่แล้วไม่ต้องเก็บ)

เริ่มทำเมื่อ: users > 50 หรือ per-user data > 2GB

## Verify deploy worked

หลัง Phase 2 เสร็จ จาก Mac terminal:
```bash
curl https://your-tunnel.trycloudflare.com/health
# → {"status":"ok"}
curl -H "X-User-Id: default" https://your-tunnel.trycloudflare.com/today
# → JSON dashboard ของ Jig
```

แล้ว Jig rebuild iOS บน Mac → dashboard โหลดผ่าน tunnel URL

---

## TaskList ตอน handoff

6 tasks สำหรับ Phase 1 (1 เสร็จ, 5 pending):
1. ✅ แยกข้อมูลต่อ user ใน parquet subdirectory (shortcut_sync.py เสร็จ — main.py ยัง)
2. ⏳ ทุก read endpoint รับ X-User-Id header
3. ⏳ Migrate existing parquet ไป users/default/
4. ⏳ iOS: UUID ตอน install + ส่ง X-User-Id
5. ⏳ Frontend: รับ ?uid query param + forward
6. ⏳ Test: สร้าง fake user sync

Session ใหม่ start จาก #2 (main.py refactor)
