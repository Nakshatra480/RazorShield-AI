"use client";
import React, { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle, XCircle, TrendingUp } from "lucide-react";
import type { ScanResult } from "@/lib/mockData";
import { getRiskLabel, getRiskBg, getScoreColor } from "@/lib/utils";

interface RiskScorecardProps {
  result: ScanResult;
}

function AnimatedCounter({ target, duration = 1800 }: { target: number; duration?: number }) {
  const [count, setCount] = useState(0);
  const startTimeRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    startTimeRef.current = null;
    setCount(0);

    const animate = (timestamp: number) => {
      if (!startTimeRef.current) startTimeRef.current = timestamp;
      const elapsed = timestamp - startTimeRef.current;
      const progress = Math.min(elapsed / duration, 1);
      // Ease out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setCount(Math.round(eased * target));
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate);
      }
    };

    rafRef.current = requestAnimationFrame(animate);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [target, duration]);

  return <span className="counter-value">{count}</span>;
}

function RiskGauge({ score, color }: { score: number; color: string }) {
  const [animated, setAnimated] = useState(false);
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const halfCirc = circumference * 0.75; // 270° arc
  const offset = animated
    ? halfCirc - (score / 100) * halfCirc
    : halfCirc;

  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 300);
    return () => clearTimeout(t);
  }, [score]);

  return (
    <div className="relative w-36 h-36 flex items-center justify-center">
      <svg
        className="absolute inset-0 w-full h-full -rotate-[135deg]"
        viewBox="0 0 128 128"
      >
        {/* Track */}
        <circle
          cx="64"
          cy="64"
          r={radius}
          fill="none"
          stroke="#1F2937"
          strokeWidth="8"
          strokeDasharray={`${halfCirc} ${circumference}`}
          strokeLinecap="round"
        />
        {/* Progress */}
        <circle
          cx="64"
          cy="64"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeDasharray={`${halfCirc} ${circumference}`}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="gauge-ring"
          style={{
            transition: "stroke-dashoffset 1.8s cubic-bezier(0.4,0,0.2,1)",
            filter: `drop-shadow(0 0 6px ${color}60)`,
          }}
        />
      </svg>

      {/* Score display */}
      <div className="text-center z-10">
        <div className="text-3xl font-bold tabular-nums" style={{ color }}>
          <AnimatedCounter target={score} />
        </div>
        <div className="text-xs text-slate-500 mt-0.5">/ 100</div>
      </div>
    </div>
  );
}

const SEVERITY_ICONS = {
  "SAFE": CheckCircle,
  "NEEDS_REVIEW": AlertTriangle,
  "HIGH_RISK": XCircle,
};

export default function RiskScorecard({ result }: RiskScorecardProps) {
  const scoreColor = getScoreColor(result.riskScore);
  const riskBg = getRiskBg(result.riskLevel);
  const RiskIcon = SEVERITY_ICONS[result.riskLevel];

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="rounded-xl border border-slate-800 bg-surface overflow-hidden"
    >
      {/* Top strip */}
      <div
        className="h-0.5"
        style={{
          background: `linear-gradient(90deg, ${scoreColor}60, ${scoreColor}20, transparent)`,
        }}
      />

      <div className="p-6">
        <div className="flex flex-col md:flex-row items-start md:items-center gap-6">
          {/* Gauge */}
          <RiskGauge score={result.riskScore} color={scoreColor} />

          {/* Right content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-3 flex-wrap">
              <h2 className="text-lg font-semibold text-white">
                Risk Assessment
              </h2>
              <span
                className={`flex items-center gap-1.5 px-3 py-1 rounded-md border text-xs font-semibold tracking-wide ${riskBg}`}
              >
                <RiskIcon className="w-3.5 h-3.5" />
                {getRiskLabel(result.riskLevel)}
              </span>
            </div>

            <div className="flex items-center gap-4 mb-4 text-sm font-mono text-slate-400">
              <span>
                <span className="text-slate-600">domain: </span>
                <span className="text-blue-400">{result.domain}</span>
              </span>
              <span className="text-slate-700">|</span>
              <span>
                <span className="text-slate-600">scan: </span>
                <span className="text-slate-400">
                  {result.totalDurationMs}ms
                </span>
              </span>
              <span className="text-slate-700">|</span>
              <span>
                <span className="text-slate-600">agents: </span>
                <span className="text-slate-400">3 / 3</span>
              </span>
            </div>

            {/* Key Drivers */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <TrendingUp className="w-3.5 h-3.5 text-slate-500" />
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
                  Key Risk Drivers
                </span>
              </div>
              <ul className="space-y-1.5">
                {result.keyDrivers.map((driver, i) => (
                  <motion.li
                    key={i}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.4 + i * 0.1 }}
                    className="flex items-start gap-2 text-xs text-slate-400"
                  >
                    <span
                      className="mt-1 flex-shrink-0 w-1.5 h-1.5 rounded-full"
                      style={{ backgroundColor: scoreColor }}
                    />
                    {driver}
                  </motion.li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        {/* Agent confidence summary row */}
        <div className="mt-6 pt-4 border-t border-slate-800 grid grid-cols-3 gap-4">
          {result.agents.map((agent) => (
            <div key={agent.id} className="text-center">
              <div className="text-xs text-slate-500 mb-1">{agent.name.replace(" Sub-Agent","")}</div>
              <div className="relative h-1 rounded-full bg-slate-800 overflow-hidden">
                <motion.div
                  className="absolute left-0 top-0 h-full rounded-full"
                  style={{ backgroundColor: scoreColor }}
                  initial={{ width: 0 }}
                  animate={{ width: `${agent.confidence}%` }}
                  transition={{ delay: 0.8, duration: 1, ease: "easeOut" }}
                />
              </div>
              <div className="text-xs font-mono text-slate-400 mt-1">
                {agent.confidence}%
                <span className="text-slate-600 ml-1">conf.</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </motion.div>
  );
}
