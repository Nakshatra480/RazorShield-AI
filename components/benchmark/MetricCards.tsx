"use client";
import React, { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { MOCK_BENCHMARK } from "@/lib/mockData";
import { TrendingUp, Target, BarChart3, DollarSign } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: number;
  unit: string;
  icon: React.ReactNode;
  color: string;
  delay?: number;
}

function AnimatedValue({
  target,
  decimals = 1,
  delay = 0,
}: {
  target: number;
  decimals?: number;
  delay?: number;
}) {
  const [val, setVal] = useState(0);
  const startRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const DURATION = 1600;
    startRef.current = null;

    const delayTimer = setTimeout(() => {
      const animate = (ts: number) => {
        if (!startRef.current) startRef.current = ts;
        const p = Math.min((ts - startRef.current) / DURATION, 1);
        const eased = 1 - Math.pow(1 - p, 3);
        setVal(parseFloat((eased * target).toFixed(decimals)));
        if (p < 1) rafRef.current = requestAnimationFrame(animate);
      };
      rafRef.current = requestAnimationFrame(animate);
    }, delay);

    return () => {
      clearTimeout(delayTimer);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [target, decimals, delay]);

  return (
    <span className="counter-value">
      {decimals === 0 ? val : val.toFixed(decimals)}
    </span>
  );
}

function MetricCard({ label, value, unit, icon, color, delay = 0 }: MetricCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4 }}
      className="rounded-xl border border-slate-800 bg-surface p-5 relative overflow-hidden"
    >
      {/* Top accent */}
      <div
        className="absolute top-0 left-0 right-0 h-0.5"
        style={{ background: color }}
      />

      <div className="flex items-start justify-between mb-3">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: `${color}15`, border: `1px solid ${color}30` }}
        >
          {icon}
        </div>
      </div>

      <div className="text-3xl font-bold text-white tabular-nums mb-1">
        {unit === "$" && (
          <span className="text-lg text-slate-500 mr-0.5">{unit}</span>
        )}
        <AnimatedValue
          target={value}
          decimals={unit === "$" ? 0 : 1}
          delay={delay * 1000}
        />
        {unit !== "$" && (
          <span className="text-lg text-slate-500 ml-0.5">{unit}</span>
        )}
      </div>

      <div className="text-xs text-slate-500 font-medium">{label}</div>
    </motion.div>
  );
}

export default function MetricCards() {
  const b = MOCK_BENCHMARK;
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <MetricCard
        label="Precision"
        value={b.precision}
        unit="%"
        icon={<Target className="w-4 h-4" style={{ color: "#10B981" }} />}
        color="#10B981"
        delay={0}
      />
      <MetricCard
        label="Recall"
        value={b.recall}
        unit="%"
        icon={<TrendingUp className="w-4 h-4" style={{ color: "#3B82F6" }} />}
        color="#3B82F6"
        delay={0.1}
      />
      <MetricCard
        label="F1-Score"
        value={b.f1Score}
        unit="%"
        icon={<BarChart3 className="w-4 h-4" style={{ color: "#6366F1" }} />}
        color="#6366F1"
        delay={0.2}
      />
      <MetricCard
        label="False Positive Cost"
        value={b.falsePositiveCost}
        unit="$"
        icon={<DollarSign className="w-4 h-4" style={{ color: "#F59E0B" }} />}
        color="#F59E0B"
        delay={0.3}
      />
    </div>
  );
}
