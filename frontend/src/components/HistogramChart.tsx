import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import { HistogramBin } from '../types';

export interface HistogramChartProps {
  data: HistogramBin[];
  thresholdDb: number;
}

export const HistogramChart: React.FC<HistogramChartProps> = ({ data, thresholdDb }) => {
  if (!data || data.length === 0) {
    return (
      <div className="h-36 flex items-center justify-center text-xs text-text-taupe italic">
        No histogram data available.
      </div>
    );
  }

  return (
    <div className="w-full">
      <div className="flex items-center justify-between text-[11px] text-text-taupe mb-1.5 font-mono">
        <span>Threshold: {thresholdDb} dB</span>
        <div className="flex items-center space-x-2">
          <span className="flex items-center">
            <span className="w-2 h-2 rounded-sm bg-alert-terracotta mr-1 inline-block" /> Change
          </span>
          <span className="flex items-center">
            <span className="w-2 h-2 rounded-sm bg-accent-espresso mr-1 inline-block" /> Nominal
          </span>
        </div>
      </div>
      <div className="h-36 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 5, right: 5, left: -25, bottom: 5 }}>
            <XAxis
              dataKey="bin"
              tick={{ fontSize: 9, fill: '#AAB7C4', fontFamily: 'JetBrains Mono' }}
              interval={1}
              stroke="#2C3E50"
            />
            <YAxis
              tick={{ fontSize: 9, fill: '#AAB7C4', fontFamily: 'JetBrains Mono' }}
              tickFormatter={(v) => (v > 1000 ? `${(v / 1000).toFixed(0)}k` : v)}
              stroke="#2C3E50"
            />
            <Tooltip
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  const item = payload[0].payload as HistogramBin;
                  return (
                    <div className="bg-surface-cream border border-border-sandstone rounded p-2 text-xs shadow-panel font-mono text-text-roast">
                      <div className="font-semibold text-text-roast">{item.bin}</div>
                      <div className="text-text-taupe">
                        Count:{' '}
                        <span className="text-accent-espresso font-bold">
                          {item.count.toLocaleString()} px
                        </span>
                      </div>
                      {item.is_change && (
                        <div className="text-alert-terracotta text-[10px] font-semibold mt-0.5">
                          Detected Anomaly
                        </div>
                      )}
                    </div>
                  );
                }
                return null;
              }}
            />
            <Bar dataKey="count" radius={[2, 2, 0, 0]}>
              {data.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={entry.is_change ? '#D85B61' : '#36CFC9'}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
