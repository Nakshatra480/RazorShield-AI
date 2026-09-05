"use client";
import React, { useState } from "react";
import { motion } from "framer-motion";
import { MOCK_BENCHMARK } from "@/lib/mockData";

interface Cell {
  label: string;
  sublabel: string;
  value: number;
  bg: string;
  text: string;
  border: string;
  definition: string;
}

const TOOLTIP_DEFS: Record<string, string> = {
  TP: "True Positives: Risky merchants correctly blocked by the system.",
  FP: "False Positives: Safe merchants incorrectly flagged. Minimizing this reduces friction.",
  TN: "True Negatives: Safe merchants correctly approved.",
  FN: "False Negatives: Risky merchants incorrectly approved. Minimizing this reduces fraud loss.",
};

export default function ConfusionMatrix() {
  const [tooltip, setTooltip] = useState<string | null>(null);
  const cm = MOCK_BENCHMARK.confusionMatrix;
  const total = cm.truePositive + cm.falsePositive + cm.trueNegative + cm.falseNegative;

  const cells: Cell[] = [
    {
      label: "True Positive",
      sublabel: "TP",
      value: cm.truePositive,
      bg: "bg-emerald-950/50",
      text: "text-emerald-400",
      border: "border-emerald-800/50",
      definition: TOOLTIP_DEFS.TP,
    },
    {
      label: "False Positive",
      sublabel: "FP",
      value: cm.falsePositive,
      bg: "bg-amber-950/30",
      text: "text-amber-400",
      border: "border-amber-800/40",
      definition: TOOLTIP_DEFS.FP,
    },
    {
      label: "False Negative",
      sublabel: "FN",
      value: cm.falseNegative,
      bg: "bg-red-950/40",
      text: "text-red-400",
      border: "border-red-800/40",
      definition: TOOLTIP_DEFS.FN,
    },
    {
      label: "True Negative",
      sublabel: "TN",
      value: cm.trueNegative,
      bg: "bg-blue-950/30",
      text: "text-blue-400",
      border: "border-blue-800/40",
      definition: TOOLTIP_DEFS.TN,
    },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2, duration: 0.4 }}
      className="rounded-xl border border-slate-800 bg-surface p-5"
    >
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-white">Confusion Matrix</h3>
        <p className="text-xs text-slate-500 mt-0.5">
          Evaluated on {total} merchant samples — hover cells for definitions
        </p>
      </div>

      {/* Axis labels */}
      <div className="relative">
        {/* Y-axis label */}
        <div className="absolute -left-4 top-1/2 -translate-y-1/2 -rotate-90">
          <span className="text-xs text-slate-600 font-mono whitespace-nowrap">
            Actual →
          </span>
        </div>

        {/* X-axis label */}
        <div className="text-center mb-1">
          <span className="text-xs text-slate-600 font-mono">Predicted →</span>
        </div>

        {/* Column headers */}
        <div className="grid grid-cols-2 gap-1 mb-1 ml-6">
          <div className="text-center text-xs text-slate-500 font-mono py-1 bg-slate-900/50 rounded">
            Predicted Risky
          </div>
          <div className="text-center text-xs text-slate-500 font-mono py-1 bg-slate-900/50 rounded">
            Predicted Safe
          </div>
        </div>

        <div className="grid grid-cols-2 gap-1 ml-6">
          {cells.map((cell, i) => (
            <div
              key={cell.sublabel}
              className="relative"
              onMouseEnter={() => setTooltip(cell.sublabel)}
              onMouseLeave={() => setTooltip(null)}
            >
              <motion.div
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ delay: 0.3 + i * 0.08 }}
                className={`rounded-lg border ${cell.bg} ${cell.border} p-4 cursor-default text-center`}
              >
                <div className={`text-2xl font-bold tabular-nums ${cell.text}`}>
                  {cell.value}
                </div>
                <div className={`text-xs font-mono font-bold mt-0.5 ${cell.text} opacity-80`}>
                  {cell.sublabel}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">{cell.label}</div>
                <div className="text-xs text-slate-600 mt-1 font-mono">
                  {((cell.value / total) * 100).toFixed(1)}%
                </div>
              </motion.div>

              {/* Tooltip */}
              {tooltip === cell.sublabel && (
                <motion.div
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 w-52 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 z-20 pointer-events-none"
                >
                  <p className="text-xs text-slate-300 leading-relaxed">
                    {cell.definition}
                  </p>
                </motion.div>
              )}
            </div>
          ))}
        </div>
      </div>
    </motion.div>
  );
}
