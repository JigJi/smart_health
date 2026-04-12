'use client';

import { useEffect, useState } from 'react';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8400';

type Tag = { id: string; label_th: string; icon: string };
type Entry = { day: string; tags: string[]; note: string };
type Insight = {
  tag: string;
  label_th: string;
  icon: string;
  n_with: number;
  n_without: number;
  hrv_with: number;
  hrv_without: number;
  hrv_diff_pct: number;
  rhr_diff: number | null;
  impact: string;
  message_th: string;
  ready: boolean;
};

export default function JournalPage() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [note, setNote] = useState('');
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10));
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState('');

  useEffect(() => {
    (async () => {
      const [t, e, i] = await Promise.all([
        fetch(`${API}/journal/tags`).then((r) => r.json()),
        fetch(`${API}/journal/entries?days=90`).then((r) => r.json()),
        fetch(`${API}/journal/insights`).then((r) => r.json()),
      ]);
      setTags(t);
      setEntries(e);
      setInsights(i);

      // Pre-fill if today already has an entry
      const today = e.find((x: Entry) => x.day === day);
      if (today) {
        setSelected(new Set(today.tags));
        setNote(today.note || '');
      }
    })();
  }, []);

  // Load entry when day picker changes
  useEffect(() => {
    const existing = entries.find((x) => x.day === day);
    if (existing) {
      setSelected(new Set(existing.tags));
      setNote(existing.note || '');
    } else {
      setSelected(new Set());
      setNote('');
    }
  }, [day, entries]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const save = async () => {
    setSaving(true);
    await fetch(`${API}/journal`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ day, tags: [...selected], note }),
    });
    const e = await fetch(`${API}/journal/entries?days=90`).then((r) => r.json());
    setEntries(e);
    setSaving(false);
    setToast('บันทึกแล้ว ✓');
    setTimeout(() => setToast(''), 2000);
  };

  const recentDays = entries.slice(-14).reverse();

  return (
    <main className="max-w-4xl mx-auto p-6 space-y-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Journal</h1>
        <a href="/" className="text-xs text-gray-500 hover:text-gray-300 underline">
          ← Dashboard
        </a>
      </header>

      {/* Day picker + Tag grid */}
      <div className="bg-panel border border-border rounded-xl p-5">
        <div className="flex items-center gap-3 mb-4">
          <label className="text-sm text-gray-400">วันที่:</label>
          <input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            className="bg-bg border border-border rounded px-3 py-1.5 text-sm text-gray-200"
          />
        </div>

        <div className="text-sm text-gray-300 mb-3">วันนี้คุณ...</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {tags.map((t) => {
            const active = selected.has(t.id);
            return (
              <button
                key={t.id}
                onClick={() => toggle(t.id)}
                className="flex items-center gap-2 px-3 py-2.5 rounded border text-sm text-left transition-colors"
                style={{
                  borderColor: active ? '#5be49b' : '#1f242e',
                  background: active ? 'rgba(91,228,155,0.1)' : 'transparent',
                  color: active ? '#5be49b' : '#94a3b8',
                }}
              >
                <span className="text-lg">{t.icon}</span>
                <span>{t.label_th}</span>
              </button>
            );
          })}
        </div>

        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="โน้ต (ไม่จำเป็น)"
          rows={2}
          className="w-full mt-4 bg-bg border border-border rounded px-3 py-2 text-sm text-gray-200 placeholder-gray-600 resize-none"
        />

        <div className="flex items-center gap-3 mt-4">
          <button
            onClick={save}
            disabled={saving}
            className="px-5 py-2 rounded font-medium text-sm bg-accent text-bg hover:brightness-110 disabled:opacity-50"
          >
            {saving ? 'กำลังบันทึก…' : 'บันทึก'}
          </button>
          {toast && <span className="text-sm text-accent">{toast}</span>}
        </div>
      </div>

      {/* Insights */}
      <div className="bg-panel border border-border rounded-xl p-5">
        <h2 className="text-sm font-medium text-gray-300 mb-4">
          Insights — พฤติกรรมที่มีผลต่อร่างกายของคุณ
        </h2>

        {insights.length === 0 && (
          <div className="text-sm text-gray-500">
            ยังไม่มี insight — บันทึกอย่างน้อย 7 วันก่อน
          </div>
        )}

        {insights.map((ins) => {
          if (!ins.ready) {
            return (
              <div key="not-ready" className="text-sm text-gray-500 mb-2">
                {ins.message_th}
              </div>
            );
          }

          const impactColor =
            ins.impact === 'positive'
              ? '#5be49b'
              : ins.impact === 'negative'
              ? '#ef5350'
              : '#94a3b8';

          return (
            <div
              key={ins.tag}
              className="flex items-start gap-3 py-3 border-b border-border last:border-0"
            >
              <div className="text-2xl mt-0.5">{ins.icon}</div>
              <div className="flex-1">
                <div className="text-sm text-gray-200">{ins.message_th}</div>
                <div className="flex items-center gap-4 mt-1 text-xs text-gray-500">
                  <span>
                    HRV:{' '}
                    <span style={{ color: impactColor }}>
                      {ins.hrv_diff_pct > 0 ? '+' : ''}
                      {ins.hrv_diff_pct}%
                    </span>
                  </span>
                  {ins.rhr_diff != null && (
                    <span>
                      RHR:{' '}
                      <span
                        style={{
                          color:
                            ins.rhr_diff > 1
                              ? '#ef5350'
                              : ins.rhr_diff < -1
                              ? '#5be49b'
                              : '#94a3b8',
                        }}
                      >
                        {ins.rhr_diff > 0 ? '+' : ''}
                        {ins.rhr_diff} bpm
                      </span>
                    </span>
                  )}
                  <span>{ins.n_with} ครั้ง</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Recent entries */}
      {recentDays.length > 0 && (
        <div className="bg-panel border border-border rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-300 mb-3">
            บันทึกล่าสุด
          </h2>
          <div className="space-y-2">
            {recentDays.map((e) => (
              <div
                key={e.day}
                className="flex items-center gap-3 text-sm border-b border-border pb-2 last:border-0"
              >
                <button
                  onClick={() => setDay(e.day)}
                  className="text-xs text-gray-400 hover:text-accent underline w-24"
                >
                  {e.day}
                </button>
                <div className="flex gap-1 flex-wrap">
                  {e.tags.map((t) => {
                    const info = tags.find((x) => x.id === t);
                    return (
                      <span
                        key={t}
                        className="inline-flex items-center gap-1 px-2 py-0.5 bg-bg border border-border rounded text-xs text-gray-400"
                      >
                        {info?.icon} {info?.label_th ?? t}
                      </span>
                    );
                  })}
                </div>
                {e.note && (
                  <span className="text-xs text-gray-500 truncate max-w-[200px]">
                    {e.note}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </main>
  );
}
