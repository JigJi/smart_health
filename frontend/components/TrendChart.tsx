'use client';

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';

type Point = Record<string, string | number | null>;

export function TrendChart({
  data,
  xKey,
  yKey,
  label,
  color = '#5be49b',
}: {
  data: Point[];
  xKey: string;
  yKey: string;
  label: string;
  color?: string;
}) {
  return (
    <div className="bg-panel border border-border rounded-lg p-4">
      <h3 className="text-sm text-gray-400 mb-2">{label}</h3>
      <div style={{ width: '100%', height: 220 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 16, left: -8, bottom: 0 }}>
            <CartesianGrid stroke="#1f242e" strokeDasharray="3 3" />
            <XAxis dataKey={xKey} stroke="#8a94a7" fontSize={11} />
            <YAxis stroke="#8a94a7" fontSize={11} />
            <Tooltip
              contentStyle={{
                background: '#141820',
                border: '1px solid #1f242e',
                borderRadius: 6,
                fontSize: 12,
              }}
            />
            <Line
              type="monotone"
              dataKey={yKey}
              stroke={color}
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
