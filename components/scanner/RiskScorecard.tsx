"use client";
import React, { useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import type { ScanResult } from "@/lib/types";
import { formatMs, getRiskBg, getRiskLabel, getScoreColor } from "@/lib/utils";

interface RiskScorecardProps {
  result: ScanResult;
}

const RISK_ICONS = {
  SAFE: CheckCircle2,
  NEEDS_REVIEW: AlertTriangle,
  HIGH_RISK: XCircle,
} as const;

function AnimatedCounter({ target, duration = 900 }: { target: number; duration?: number }) {
  const reduceMotion = useReducedMotion();
  const [count, setCount] = useState(reduceMotion ? target : 0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (reduceMotion) {
      setCount(target);
      return;
    }
    let start: number | null = null;
    const step = (ts: number) => {
      if (start === null) start = ts;
      const progress = Math.min((ts - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setCount(Math.round(eased * target));
      if (progress < 1) rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [target, duration, reduceMotion]);

  return <>{count}</>;
}

/**
 * 270° gauge. The arc is drawn on a light track so the remaining capacity stays
 * visible — a dark-theme glow would disappear entirely against white.
 */
function RiskGauge({ score, color }: { score: number; color: string }) {
  const reduceMotion = useReducedMotion();
  const [animated, setAnimated] = useState(reduceMotion);
  const radius = 56;
  const circumference = 2 * Math.PI * radius;
  const arc = circumference * 0.75;
  const clamped = Math.max(0, Math.min(100, score));
  const offset = animated ? arc - (clamped / 100) * arc : arc;

  useEffect(() => {
    if (reduceMotion) return;
    const t = setTimeout(() => setAnimated(true), 120);
    return () => clearTimeout(t);
  }, [score, reduceMotion]);

  return (
    <div className="relative w-[136px] h-[136px] flex items-center justify-center flex-shrink-0">
      <svg
        className="absolute inset-0 w-full h-full -rotate-[135deg]"
        viewBox="0 0 128 128"
        aria-hidden
      >
        <circle
          cx="64"
          cy="64"
          r={radius}
          fill="none"
          stroke="#EDF1F7"
          strokeWidth="9"
          strokeDasharray={`${arc} ${circumference}`}
          strokeLinecap="round"
        />
        <circle
          cx="64"
          cy="64"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="9"
          strokeDasharray={`${arc} ${circumference}`}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{
            transition: reduceMotion
              ? undefined
              : "stroke-dashoffset 1.1s cubic-bezier(0.4,0,0.2,1)",
          }}
        />
      </svg>
      <div className="text-center">
        <div className="text-[34px] leading-none font-semibold tabular-nums" style={{ color }}>
          <AnimatedCounter target={Math.round(clamped)} />
        </div>
        <div className="text-[11px] text-ink-3 mt-1">of 100</div>
      </div>
    </div>
  );
}

export default function RiskScorecard({ result }: RiskScorecardProps) {
  const scoreColor = getScoreColor(result.riskScore);
  const RiskIcon = RISK_ICONS[result.riskLevel];

  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="rounded-xl border border-line bg-surface shadow-card overflow-hidden"
    >
      <div className="p-6">
        <div className="flex flex-col md:flex-row items-start gap-7">
          <RiskGauge score={result.riskScore} color={scoreColor} />

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-[12px] font-semibold ${getRiskBg(
                  result.riskLevel
                )}`}
              >
                <RiskIcon className="w-3.5 h-3.5" aria-hidden />
                {getRiskLabel(result.riskLevel)}
              </span>
              {!result.fullyAnalyzed && (
                <span
                  title={result.degradedReasons.join(" · ")}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-risk-warn-border bg-risk-warn-soft text-risk-warn text-[12px] font-medium"
                >
                  <Info className="w-3.5 h-3.5" aria-hidden />
                  Degraded analysis
                </span>
              )}
            </div>

            <h2 className="mt-3 text-[19px] font-semibold tracking-tight text-ink break-all">
              {result.domain}
            </h2>

            <dl className="mt-3 flex items-center gap-x-6 gap-y-1 flex-wrap text-[13px]">
              <div className="flex items-center gap-1.5">
                <dt className="text-ink-3">Scan time</dt>
                <dd className="font-mono text-ink-2 tabular-nums">
                  {formatMs(result.totalDurationMs)}
                </dd>
              </div>
              <div className="flex items-center gap-1.5">
                <dt className="text-ink-3">Agents</dt>
                <dd className="font-mono text-ink-2">{result.agents.length} of 3</dd>
              </div>
              <div className="flex items-center gap-1.5">
                <dt className="text-ink-3">Policy</dt>
                <dd className="font-mono text-ink-2 tabular-nums">
                  {result.agents.find((a) => a.id === "policy")?.confidence ?? 0}/100
                </dd>
              </div>
              <div className="flex items-center gap-1.5">
                <dt className="text-ink-3">Catalog</dt>
                <dd className="font-mono text-ink-2 tabular-nums">
                  {result.agents.find((a) => a.id === "catalog")?.confidence ?? 0}/100
                </dd>
              </div>
            </dl>

            {/* Degraded-mode explanation — states exactly which signal fell back */}
            {!result.fullyAnalyzed && result.degradedReasons.length > 0 && (
              <div className="mt-4 rounded-lg border border-risk-warn-border bg-risk-warn-soft px-3.5 py-3">
                <p className="text-[12px] font-semibold text-risk-warn">
                  This verdict did not use every signal
                </p>
                <ul className="mt-1.5 space-y-0.5">
                  {result.degradedReasons.map((reason, i) => (
                    <li key={i} className="text-[12px] text-ink-2 leading-relaxed">
                      • {reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-5">
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                Key risk drivers
              </h3>
              <ul className="mt-2 space-y-1.5">
                {result.keyDrivers.map((driver, i) => (
                  <li key={i} className="flex items-start gap-2 text-[13px] text-ink-2">
                    <span
                      className="mt-[7px] flex-shrink-0 w-1.5 h-1.5 rounded-full"
                      style={{ backgroundColor: scoreColor }}
                      aria-hidden
                    />
                    <span className="leading-relaxed">{driver}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>

      {/* Per-agent confidence */}
      <div className="border-t border-line bg-surface-muted/60 px-6 py-4 grid grid-cols-1 sm:grid-cols-3 gap-5">
        {result.agents.map((agent) => (
          <div key={agent.id}>
            <div className="flex items-baseline justify-between mb-1.5">
              <span className="text-[12px] text-ink-2">{agent.name}</span>
              <span className="text-[12px] font-mono text-ink tabular-nums">
                {agent.confidence}%
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-surface-sunken overflow-hidden">
              <motion.div
                className="h-full rounded-full"
                style={{ backgroundColor: scoreColor }}
                initial={{ width: 0 }}
                animate={{ width: `${Math.max(0, Math.min(100, agent.confidence))}%` }}
                transition={{ delay: 0.3, duration: 0.7, ease: "easeOut" }}
              />
            </div>
          </div>
        ))}
      </div>
    </motion.section>
  );
}
