"use client";
import React from "react";
import { motion } from "framer-motion";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { MOCK_BENCHMARK } from "@/lib/mockData";
import { TrendingDown } from "lucide-react";

const CustomTooltip = ({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) => {
  if (!active || !payload || !payload.length) return null;

  return (
    <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2.5 text-xs shadow-xl">
      <p className="text-slate-400 font-mono mb-2">{label}</p>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2 mb-1">
          <span
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{ background: p.color }}
          />
          <span className="text-slate-400">{p.name}:</span>
          <span className="font-semibold text-white">
            ${p.value.toLocaleString()}
          </span>
        </div>
      ))}
      {payload.length === 2 && (
        <div className="mt-2 pt-1.5 border-t border-slate-800">
          <span className="text-emerald-400 font-mono">
            Savings:{" "}
            <span className="font-bold">
              ${(payload[0].value - payload[1].value).toLocaleString()}
            </span>
          </span>
        </div>
      )}
    </div>
  );
};

export default function FinancialImpactChart() {
  const data = MOCK_BENCHMARK.financialImpact;

  const totalTraditional = data.reduce((s, d) => s + d.traditional, 0);
  const totalRazorshield = data.reduce((s, d) => s + d.razorshield, 0);
  const savings = totalTraditional - totalRazorshield;
  const savingsPct = ((savings / totalTraditional) * 100).toFixed(1);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3, duration: 0.4 }}
      className="rounded-xl border border-slate-800 bg-surface p-5"
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-5">
        <div>
          <h3 className="text-sm font-semibold text-white">
            Financial Loss Prevention
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Traditional Rule Engine vs. RazorShield AI — monthly fraud losses
          </p>
        </div>
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-900/20 border border-emerald-800/40">
          <TrendingDown className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-xs font-bold text-emerald-400">
            {savingsPct}% reduction
          </span>
        </div>
      </div>

      {/* Savings callout */}
      <div className="grid grid-cols-3 gap-3 mb-5">
        {[
          {
            label: "Traditional Loss",
            value: `$${(totalTraditional / 1000).toFixed(0)}k`,
            color: "text-red-400",
          },
          {
            label: "RazorShield Loss",
            value: `$${(totalRazorshield / 1000).toFixed(0)}k`,
            color: "text-blue-400",
          },
          {
            label: "Total Savings",
            value: `$${(savings / 1000).toFixed(0)}k`,
            color: "text-emerald-400",
          },
        ].map(({ label, value, color }) => (
          <div
            key={label}
            className="rounded-lg bg-slate-900/60 border border-slate-800 px-3 py-2.5 text-center"
          >
            <div className={`text-lg font-bold tabular-nums ${color}`}>
              {value}
            </div>
            <div className="text-xs text-slate-500 mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      {/* Chart */}
      <div className="h-52">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={data}
            margin={{ top: 4, right: 4, left: -16, bottom: 0 }}
          >
            <defs>
              <linearGradient
                id="gradTraditional"
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop offset="5%" stopColor="#EF4444" stopOpacity={0.2} />
                <stop offset="95%" stopColor="#EF4444" stopOpacity={0} />
              </linearGradient>
              <linearGradient
                id="gradRazorshield"
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.2} />
                <stop offset="95%" stopColor="#3B82F6" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#1F2937"
              vertical={false}
            />
            <XAxis
              dataKey="month"
              tick={{ fill: "#6B7280", fontSize: 11, fontFamily: "monospace" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: "#6B7280", fontSize: 10, fontFamily: "monospace" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              formatter={(value) => (
                <span
                  style={{
                    color: "#9CA3AF",
                    fontSize: "11px",
                    fontFamily: "monospace",
                  }}
                >
                  {value}
                </span>
              )}
            />
            <Area
              type="monotone"
              dataKey="traditional"
              name="Traditional Engine"
              stroke="#EF4444"
              strokeWidth={1.5}
              fill="url(#gradTraditional)"
            />
            <Area
              type="monotone"
              dataKey="razorshield"
              name="RazorShield AI"
              stroke="#3B82F6"
              strokeWidth={1.5}
              fill="url(#gradRazorshield)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </motion.div>
  );
}
