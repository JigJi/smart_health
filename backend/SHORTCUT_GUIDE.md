# Apple Shortcut Setup — Auto Sync Health Data

## Overview
สร้าง Shortcut บน iPhone ที่ดึง Apple Health data → ส่งเข้า backend ทุกวัน

## ขั้นตอนสร้าง Shortcut

### 1. เปิด Shortcuts app บน iPhone

### 2. กด + สร้าง Shortcut ใหม่ ตั้งชื่อ "Sync Health"

### 3. เพิ่ม Actions ตามลำดับ:

#### Step 1: Find Health Samples (Heart Rate)
```
Action: Find Health Samples
Type: Heart Rate
Starting Date: is in the last 24 hours
Sort by: Start Date
Order: Latest First
Limit: 500
```

#### Step 2: Build JSON for Heart Rate
```
Action: Set Variable
Variable: hr_json
Value: (repeat with each from Step 1)
  → {"time": "[Start Date]", "value": [Value]}
```

Actually, Shortcuts JSON building is complex.
Easier approach: use "Get Contents of URL" with Shortcuts' built-in JSON.

#### Simplified approach — use "Get Contents of URL" directly:

```
1. Find Health Samples
   Type: Heart Rate
   Period: Last 24 hours
   Limit: 500

2. Repeat with Each (Health Samples)
   → Text: {"time":"[Start Date]","value":[Value]}
   → Add to Variable: hr_list

3. Text: {"heart_rate":[hr_list joined by ","]}

4. Get Contents of URL
   URL: http://YOUR_SERVER_IP:8400/sync
   Method: POST
   Headers: Content-Type = application/json
   Request Body: (text from step 3)
```

### Alternative: Copy-paste Shortcut (recommended)

ง่ายกว่ามาก — ใช้ Toolbox Pro (ฟรี) หรือ copy Shortcut ที่มีคนทำแล้ว

## Backend URL

Replace YOUR_SERVER_IP with:
- If on same WiFi: your computer's local IP (e.g., 192.168.1.100)
- If remote: use ngrok or Tailscale

```bash
# Find your local IP:
ipconfig | grep IPv4

# Or use ngrok for remote access:
ngrok http 8400
```

## Setup Automation (auto-run daily)

1. Open Shortcuts app
2. Go to "Automation" tab
3. Tap "+" → "Personal Automation"
4. Select "Time of Day" → 7:00 AM → Daily
5. Add action: "Run Shortcut" → select "Sync Health"
6. Turn OFF "Ask Before Running"

Done! Health data will sync to backend every morning at 7 AM.

## Testing

POST test data:
```bash
curl -X POST http://localhost:8400/sync \
  -H "Content-Type: application/json" \
  -d '{"heart_rate":[{"time":"2026-04-12T09:00:00+0700","value":72}]}'
```

## Format Reference

```json
{
  "heart_rate": [
    {"time": "2026-04-12T09:00:00+0700", "value": 72}
  ],
  "hrv": [
    {"time": "2026-04-12T06:00:00+0700", "value": 35.5}
  ],
  "resting_heart_rate": [
    {"time": "2026-04-12T08:00:00+0700", "value": 65}
  ],
  "workouts": [
    {
      "type": "TraditionalStrengthTraining",
      "start": "2026-04-12T17:00:00+0700",
      "end": "2026-04-12T18:00:00+0700",
      "duration_min": 55,
      "hr_avg": 120,
      "hr_max": 155
    }
  ],
  "steps": [
    {"time": "2026-04-12T12:00:00+0700", "value": 5432}
  ],
  "active_energy": [
    {"time": "2026-04-12T12:00:00+0700", "value": 250}
  ]
}
```
