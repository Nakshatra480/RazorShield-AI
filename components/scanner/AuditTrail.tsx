"use client";
import React, { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Terminal,
  Download,
  ShieldAlert,
  CheckCircle,
  AlertTriangle,
  XCircle,
  Info,
} from "lucide-react";
import type { ScanResult, AuditStep } from "@/lib/mockData";

const LEVEL_STYLES = {
  info: {
    icon: Info,
    cls: "text-blue-400",
    prefix: "INFO ",
    agentCls: "text-slate-500",
  },
  warn: {
    icon: AlertTriangle,
    cls: "text-amber-400",
    prefix: "WARN ",
    agentCls: "text-amber-500",
  },
  error: {
    icon: XCircle,
    cls: "text-red-400",
    prefix: "ERR  ",
    agentCls: "text-red-500",
  },
  success: {
    icon: CheckCircle,
    cls: "text-emerald-400",
    prefix: "OK   ",
    agentCls: "text-emerald-500",
  },
};

function AuditLine({ step, index }: { step: AuditStep; index: number }) {
  const [visible, setVisible] = useState(false);
  const style = LEVEL_STYLES[step.level];

  useEffect(() => {
    const t = setTimeout(() => setVisible(true), index * 90);
    return () => clearTimeout(t);
  }, [index]);

  if (!visible) return null;

  return (
    <motion.div
      initial={{ opacity: 0, x: -4 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.2 }}
      className="flex items-start gap-2 py-0.5 hover:bg-white/[0.02] px-2 -mx-2 rounded group"
    >
      <span className="text-slate-700 select-none mt-0.5 flex-shrink-0 font-mono text-xs">
        {step.timestamp}
      </span>
      <span className={`font-mono text-xs flex-shrink-0 mt-0.5 ${style.cls}`}>
        {style.prefix}
      </span>
      <span className={`font-mono text-xs flex-shrink-0 mt-0.5 w-24 truncate ${style.agentCls}`}>
        [{step.agent}]
      </span>
      <div className="flex-1 min-w-0">
        <span className="text-xs font-mono text-slate-400 mr-2">{step.action}</span>
        <span className="text-xs font-mono text-slate-300">{step.result}</span>
      </div>
    </motion.div>
  );
}

interface AuditTrailProps {
  result: ScanResult;
}

export default function AuditTrail({ result }: AuditTrailProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [overrideOpen, setOverrideOpen] = useState(false);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [result.auditTrail]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3, duration: 0.4 }}
      className="rounded-xl border border-slate-800 bg-surface overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
            Audit & Decision Trail
          </span>
          <span className="text-xs font-mono text-slate-600">
            · {result.auditTrail.length} events
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            id="export-audit-pdf-btn"
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors font-medium"
            onClick={() => alert("PDF export — connect your backend to generate report")}
          >
            <Download className="w-3 h-3" />
            Export PDF
          </button>
          <button
            id="override-decision-btn"
            onClick={() => setOverrideOpen(!overrideOpen)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md bg-indigo-900/40 hover:bg-indigo-800/50 text-indigo-400 border border-indigo-800/50 transition-colors font-medium"
          >
            <ShieldAlert className="w-3 h-3" />
            Override Decision
          </button>
        </div>
      </div>

      {/* Override Panel */}
      {overrideOpen && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className="border-b border-slate-800 bg-indigo-950/20 px-5 py-3"
        >
          <p className="text-xs text-slate-400 mb-2">
            Manual override reason — will be logged to audit trail:
          </p>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Enter justification for override..."
              className="flex-1 bg-slate-900 border border-slate-700 rounded-md px-3 py-2 text-xs font-mono text-slate-300 outline-none focus:border-indigo-500/60 placeholder:text-slate-600"
            />
            <button className="px-4 py-2 text-xs rounded-md bg-indigo-600 hover:bg-indigo-500 text-white font-medium transition-colors">
              Approve Override
            </button>
            <button
              onClick={() => setOverrideOpen(false)}
              className="px-3 py-2 text-xs rounded-md bg-slate-800 hover:bg-slate-700 text-slate-400 transition-colors"
            >
              Cancel
            </button>
          </div>
        </motion.div>
      )}

      {/* Terminal body */}
      <div
        ref={scrollRef}
        className="terminal-panel px-4 py-4 max-h-80 overflow-auto"
      >
        {/* Cursor header */}
        <div className="text-slate-600 font-mono text-xs mb-3 pb-2 border-b border-slate-800/60">
          <span className="text-blue-500">razorshield</span>
          <span className="text-slate-500">@inspector</span>
          <span className="text-slate-600">:~$ </span>
          <span className="text-slate-400">
            audit --domain {result.domain} --full-trace
          </span>
        </div>

        <div className="space-y-0.5">
          {result.auditTrail.map((step, i) => (
            <AuditLine key={i} step={step} index={i} />
          ))}
        </div>

        {/* Trailing cursor */}
        <div className="mt-2 text-slate-600 font-mono text-xs typewriter-cursor">
          &nbsp;
        </div>
      </div>
    </motion.div>
  );
}
