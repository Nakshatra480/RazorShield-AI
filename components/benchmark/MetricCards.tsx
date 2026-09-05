"use client";
import React, { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  Play,
  RefreshCw,
} from "lucide-react";
import { useBenchmarkData } from "@/hooks/useBenchmarkData";

/**
 * Four headline ratios. Per the "is it even a chart?" heuristic these are single
 * numbers, so they render as stat tiles rather than four one-bar charts. Colour
 * is carried by a small status dot, never by the numeral itself.
 */
function AnimatedValue({ target, decimals = 1 }: { target: number; decimals?: number }) {
  const reduceMotion = useReducedMotion();
  const [val, setVal] = useState(reduceMotion ? target : 0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (reduceMotion) {
      setVal(target);
      return;
    }
    const DURATION = 850;
    let start: number | null = null;
    const step = (ts: number) => {
      if (start === null) start = ts;
      const p = Math.min((ts - start) / DURATION, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setVal(eased * target);
      if (p < 1) rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [target, reduceMotion]);

  return <>{val.toFixed(decimals)}</>;
}

function StatTile({
  label,
  value,
  hint,
  isPlaceholder,
}: {
  label: string;
  value: number;
  hint: string;
  isPlaceholder: boolean;
}) {
  return (
    <div className="rounded-xl border border-line bg-surface shadow-card p-5">
      <div className="text-[12px] font-medium text-ink-3">{label}</div>
      <div className="mt-2 text-[30px] leading-none font-semibold text-ink tabular-nums">
        {isPlaceholder ? (
          <span className="text-ink-4">—</span>
        ) : (
          <>
            <AnimatedValue target={value} />
            <span className="text-[17px] text-ink-3 ml-0.5">%</span>
          </>
        )}
      </div>
      <div className="mt-2 text-[12px] text-ink-3 leading-snug">{hint}</div>
    </div>
  );
}

const RUN_STATE_UI = {
  idle: { label: "Run benchmark", Icon: Play, spin: false },
  triggering: { label: "Starting…", Icon: Loader2, spin: true },
  running: { label: "Running…", Icon: Loader2, spin: true },
  done: { label: "Run again", Icon: CheckCircle2, spin: false },
  error: { label: "Retry", Icon: AlertCircle, spin: false },
} as const;

export default function MetricCards() {
  const { data, loading, refetch, triggerBenchmark, runState, runMessage } =
    useBenchmarkData();

  const ui = RUN_STATE_UI[runState];
  const BtnIcon = ui.Icon;
  const busy = runState === "triggering" || runState === "running";
  const noResults = data.isMock || !data.generatedAt;

  return (
    <div className="space-y-3">
      {/* Provenance bar — states plainly whether these are measurements */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        {noResults ? (
          <p className="text-[13px] text-ink-3">
            No benchmark has been run yet. Run one to populate these metrics.
          </p>
        ) : (
          <p className="text-[13px] text-ink-3">
            <span className="inline-flex items-center gap-1.5 mr-2">
              <span className="w-1.5 h-1.5 rounded-full bg-risk-safe" aria-hidden />
              <span className="font-medium text-ink-2">
                {data.totalMerchants} merchants
              </span>
            </span>
            evaluated {new Date(data.generatedAt!).toLocaleString()}
            {data.degradedEvaluations > 0 && (
              <span className="text-risk-warn">
                {" "}· {data.degradedEvaluations} ran degraded
              </span>
            )}
          </p>
        )}

        <div className="flex items-center gap-2">
          <button
            onClick={refetch}
            disabled={loading}
            title="Reload results"
            aria-label="Reload results"
            className="p-2 rounded-lg border border-line text-ink-3 hover:text-ink-2 hover:bg-surface-muted transition-colors disabled:opacity-40"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden />
          </button>
          <button
            id="run-benchmark-btn"
            onClick={() => triggerBenchmark()}
            disabled={busy}
            className={`flex items-center gap-1.5 px-3.5 py-2 text-[13px] font-medium rounded-lg border transition-colors ${
              busy
                ? "bg-surface-muted text-ink-3 border-line cursor-not-allowed"
                : runState === "error"
                ? "bg-risk-danger-soft text-risk-danger border-risk-danger-border hover:bg-risk-danger-soft/70"
                : "bg-brand text-white border-brand hover:bg-brand-hover"
            }`}
          >
            <BtnIcon className={`w-3.5 h-3.5 ${ui.spin ? "animate-spin" : ""}`} aria-hidden />
            {ui.label}
          </button>
        </div>
      </div>

      <AnimatePresence>
        {runMessage && (
          <motion.div
            key={runState}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            role="status"
            className={`px-3.5 py-2.5 rounded-lg border text-[12px] ${
              runState === "error"
                ? "border-risk-danger-border bg-risk-danger-soft text-risk-danger"
                : runState === "done"
                ? "border-risk-safe-border bg-risk-safe-soft text-risk-safe"
                : "border-line bg-surface-muted text-ink-2"
            }`}
          >
            {runMessage}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile
          label="Precision"
          value={data.precision}
          hint="Of merchants flagged risky, how many truly were"
          isPlaceholder={noResults}
        />
        <StatTile
          label="Recall"
          value={data.recall}
          hint="Of truly risky merchants, how many were caught"
          isPlaceholder={noResults}
        />
        <StatTile
          label="F1 score"
          value={data.f1Score}
          hint="Harmonic mean of precision and recall"
          isPlaceholder={noResults}
        />
        <StatTile
          label="Accuracy"
          value={data.accuracy}
          hint="Share of all verdicts that were correct"
          isPlaceholder={noResults}
        />
      </div>
    </div>
  );
}
