"use client";
import React from "react";
import { motion } from "framer-motion";
import { useBenchmarkData } from "@/hooks/useBenchmarkData";

/**
 * 2×2 outcome matrix.
 *
 * The four cells are *states*, not a series, so they carry status colour
 * (correct → good, false decline → warning, missed fraud → critical) rather
 * than categorical hues. Each cell is also labelled in text, so the meaning
 * never depends on colour alone.
 */
interface Cell {
  key: "TP" | "FP" | "FN" | "TN";
  title: string;
  value: number;
  tone: string;
  meaning: string;
}

export default function ConfusionMatrix() {
  const { data } = useBenchmarkData();
  const cm = data.confusionMatrix;
  const total = cm.truePositive + cm.falsePositive + cm.trueNegative + cm.falseNegative;
  const hasData = total > 0 && !data.isMock;

  // Row = actual, column = predicted. Reading order matches the axis labels.
  const cells: Cell[] = [
    {
      key: "TP",
      title: "True positive",
      value: cm.truePositive,
      tone: "border-risk-safe-border bg-risk-safe-soft text-risk-safe",
      meaning: "Risky merchant correctly blocked",
    },
    {
      key: "FN",
      title: "False negative",
      value: cm.falseNegative,
      tone: "border-risk-danger-border bg-risk-danger-soft text-risk-danger",
      meaning: "Risky merchant wrongly approved — the costly error",
    },
    {
      key: "FP",
      title: "False positive",
      value: cm.falsePositive,
      tone: "border-risk-warn-border bg-risk-warn-soft text-risk-warn",
      meaning: "Safe merchant wrongly blocked — adds onboarding friction",
    },
    {
      key: "TN",
      title: "True negative",
      value: cm.trueNegative,
      tone: "border-risk-safe-border bg-risk-safe-soft text-risk-safe",
      meaning: "Safe merchant correctly approved",
    },
  ];

  return (
    <section className="rounded-xl border border-line bg-surface shadow-card p-5">
      <div className="mb-4">
        <h2 className="text-[15px] font-semibold text-ink">Outcome matrix</h2>
        <p className="text-[12px] text-ink-3 mt-0.5">
          {hasData
            ? `${total} labelled merchants from the most recent run`
            : "Run a benchmark to populate this matrix"}
        </p>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[auto_1fr_1fr] gap-2 items-center">
        <span aria-hidden />
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3 text-center pb-1">
          Predicted risky
        </span>
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3 text-center pb-1">
          Predicted safe
        </span>

        {/* Row: actually risky */}
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3 pr-1 text-right leading-tight">
          Actually
          <br />
          risky
        </span>
        {[cells[0], cells[1]].map((cell, i) => (
          <MatrixCell key={cell.key} cell={cell} total={total} hasData={hasData} delay={i * 0.06} />
        ))}

        {/* Row: actually safe */}
        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3 pr-1 text-right leading-tight">
          Actually
          <br />
          safe
        </span>
        {[cells[2], cells[3]].map((cell, i) => (
          <MatrixCell
            key={cell.key}
            cell={cell}
            total={total}
            hasData={hasData}
            delay={(i + 2) * 0.06}
          />
        ))}
      </div>

      <dl className="mt-4 pt-4 border-t border-line space-y-1.5">
        {cells.map((cell) => (
          <div key={cell.key} className="flex items-start gap-2 text-[12px]">
            <dt className="font-mono font-semibold text-ink-2 w-6 flex-shrink-0">{cell.key}</dt>
            <dd className="text-ink-3 leading-snug">{cell.meaning}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function MatrixCell({
  cell,
  total,
  hasData,
  delay,
}: {
  cell: Cell;
  total: number;
  hasData: boolean;
  delay: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay, duration: 0.25 }}
      className={`rounded-lg border p-4 text-center ${cell.tone}`}
    >
      <div className="text-[26px] font-semibold tabular-nums leading-none">
        {hasData ? cell.value : "—"}
      </div>
      <div className="text-[11px] font-semibold mt-1.5 opacity-90">{cell.key}</div>
      <div className="text-[11px] text-ink-3 mt-0.5">{cell.title}</div>
      {hasData && total > 0 && (
        <div className="text-[11px] text-ink-4 mt-1 tabular-nums">
          {((cell.value / total) * 100).toFixed(1)}%
        </div>
      )}
    </motion.div>
  );
}
