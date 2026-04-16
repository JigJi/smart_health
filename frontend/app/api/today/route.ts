import { NextResponse } from 'next/server';
import { NextRequest } from 'next/server';

const BACKEND = process.env.BACKEND_URL || 'http://localhost:8401';

/**
 * Build a synthetic stress payload for UI iteration when real parquet
 * data is stale (e.g., Mac dev backend hasn't synced from iPhone in
 * days). Trigger with ?mock=1.
 *
 * Models a typical day so we can verify chart visuals across all states:
 *   - Sleep block at start (low stress, fluctuating with sleep stages)
 *   - Wake-up rise
 *   - Morning workout spike (75-95)
 *   - Post-workout recovery
 *   - Daytime variable
 *   - Watch-off gap mid-afternoon
 *   - Evening continuation
 */
function buildMockStress() {
  // Cycle starts at last bedtime (= 23:00 yesterday).
  const now = new Date();
  const cycleStart = new Date(now);
  cycleStart.setDate(cycleStart.getDate() - 1);
  cycleStart.setHours(23, 0, 0, 0);

  // Generate samples roughly every 5 min, but with a deliberate gap
  // to test gap-break rendering. LAST_MINS extends to "right now" so
  // the chart ends at the current moment (= live-data feel) and the
  // big "current value" matches the chart's last point.
  const timeline: { time: string; stress: number }[] = [];
  const SAMPLE_MINS = 5;
  const GAP_START = 15 * 60;     // 14:00 next day = 15h after bedtime
  const GAP_END   = 17 * 60;     // 16:00 next day = 17h after bedtime
  const minsToNow = (now.getTime() - cycleStart.getTime()) / 60_000;
  const LAST_MINS = Math.min(24 * 60, Math.max(60, Math.floor(minsToNow)));

  // Stress profile by hour-from-cycle-start (24h cycle).
  // Hours 0-8: sleep (low, 8-25, dips deeper mid-sleep)
  // Hour 8-9:  wake (rise to 35)
  // Hour 9-10: workout (spike 70-95)
  // Hour 10-11: cooldown (50→30)
  // Hour 11-13: morning work (35-55)
  // Hour 13-14: lunch (25-40)
  // Hour 14-15: afternoon work (40-60)
  // Hour 15-17: WATCH OFF (gap)
  // Hour 17-22: evening (30-50)
  function profile(h: number, jitter: number): number {
    let base: number;
    if (h < 1) base = 22 - h * 8;            // falling into sleep
    else if (h < 4) base = 14 - (h - 1) * 1.5;  // deep sleep
    else if (h < 7) base = 10 + (h - 4) * 1;    // light sleep
    else if (h < 8) base = 13 + (h - 7) * 22;   // wake-up rise
    else if (h < 9) base = 35 + (h - 8) * 50;   // workout ramp
    else if (h < 10) base = 85 + Math.sin((h - 9) * 6) * 8;  // workout peak
    else if (h < 11) base = 85 - (h - 10) * 50;  // cooldown
    else if (h < 13) base = 40 + Math.sin(h * 2) * 10;
    else if (h < 14) base = 30 + Math.sin(h * 3) * 5;
    else if (h < 15) base = 50 + Math.sin(h * 2) * 8;
    else base = 40 + Math.sin(h * 1.5) * 8;
    return Math.max(5, Math.min(100, Math.round(base + jitter)));
  }

  for (let m = 0; m <= LAST_MINS; m += SAMPLE_MINS) {
    if (m >= GAP_START && m <= GAP_END) continue;  // watch off
    const h = m / 60;
    const jitter = (Math.sin(m * 0.7) + Math.sin(m * 1.9)) * 4;
    const stress = profile(h, jitter);
    const t = new Date(cycleStart.getTime() + m * 60_000);
    timeline.push({ time: t.toISOString(), stress });
  }

  const stresses = timeline.map(t => t.stress);
  const current = stresses[stresses.length - 1];
  const lastTime = timeline[timeline.length - 1].time;

  return {
    acute: current,
    current,
    highest: Math.max(...stresses),
    lowest: Math.min(...stresses),
    peak: Math.max(...stresses),
    peak_time: timeline.find(t => t.stress === Math.max(...stresses))?.time ?? null,
    avg: Math.round(stresses.reduce((a, b) => a + b, 0) / stresses.length),
    timeline,
    latest_sample_time: lastTime,
    latest_hr_sample_time: lastTime,
    cycle_start: cycleStart.toISOString(),
    weekly_avg: 38,
    weekly_trend: -2,
    cv: 18.5,
    stability: 'variable',
  };
}

export async function GET(request: NextRequest) {
  try {
    const date = request.nextUrl.searchParams.get('date');
    const uid = request.nextUrl.searchParams.get('uid') || 'default';
    const mock = request.nextUrl.searchParams.get('mock');
    const url = date ? `${BACKEND}/today?date=${date}` : `${BACKEND}/today`;
    const res = await fetch(url, { cache: 'no-store', headers: { 'X-User-Id': uid } });
    const data = await res.json();
    if (mock === '1') {
      // Override the stress block with a synthetic full-day timeline
      // so we can iterate on chart UI when real parquet data is stale.
      data.stress = buildMockStress();
      // Also override the `date` to today so the live-day check (isLive)
      // returns true and we exercise the live-rendering branches.
      const now = new Date();
      data.date = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
      // Provide bedtime/wakeup so the sleep band renders.
      data.sleep = { ...(data.sleep || {}), bedtime: '23:00', wakeup: '07:00' };
      // Mock workout — strength training at 08:00, 60 min — places a
      // 🏋️ icon on the chart aligned with the morning workout spike.
      data.strain = {
        ...(data.strain || { steps: 0, active_kcal: 350, label: 'normal' }),
        workouts: [
          { type: 'strength', duration_min: 60, kcal: 350, time: '08:00' },
        ],
      };
    }
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: 'backend unreachable' }, { status: 502 });
  }
}
