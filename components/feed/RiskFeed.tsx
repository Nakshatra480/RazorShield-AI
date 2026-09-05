"use client";
import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Activity,
  Filter,
  ChevronRight,
  CheckCircle,
  AlertTriangle,
  XCircle,
  Clock,
  Shield,
  Package,
  Globe,
} from "lucide-react";
import { MOCK_FEED, type FeedEntry, type RiskLevel } from "@/lib/mockData";
import { getRiskBg, formatTimestamp } from "@/lib/utils";

const RISK_ICONS = {
  SAFE: CheckCircle,
  NEEDS_REVIEW: AlertTriangle,
  HIGH_RISK: XCircle,
};

const AGENT_LABELS: Record<string, { icon: typeof Shield; label: string }> = {
  POLICY_AGENT: { icon: Shield, label: "Policy" },
  CATALOG_AGENT: { icon: Package, label: "Catalog" },
  FOOTPRINT_AGENT: { icon: Globe, label: "Footprint" },
};

const DECISION_STYLES: Record<string, string> = {
  APPROVED: "text-emerald-400 bg-emerald-900/20 border-emerald-800/40",
  MANUAL_REVIEW: "text-amber-400 bg-amber-900/20 border-amber-800/40",
  BLOCKED: "text-red-400 bg-red-900/20 border-red-800/40",
};

type Filter = "ALL" | RiskLevel;

function FeedRow({ entry }: { entry: FeedEntry }) {
  const [expanded, setExpanded] = useState(false);
  const RiskIcon = RISK_ICONS[entry.riskLevel];
  const riskBg = getRiskBg(entry.riskLevel);
  const decisionCls = DECISION_STYLES[entry.decision] ?? "";

  return (
    <div className="border-b border-slate-800/70 last:border-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-4 px-5 py-3.5 hover:bg-slate-800/30 transition-colors text-left"
      >
        {/* Risk badge */}
        <span
          className={`flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-semibold tracking-wide w-36 flex-shrink-0 ${riskBg}`}
        >
          <RiskIcon className="w-3 h-3" />
          {entry.riskLevel === "NEEDS_REVIEW"
            ? "REVIEW"
            : entry.riskLevel}
        </span>

        {/* Domain */}
        <span className="flex-1 text-sm font-mono text-slate-200 truncate">
          {entry.domain}
        </span>

        {/* Score */}
        <div className="w-12 text-right flex-shrink-0">
          <span className="text-sm font-bold tabular-nums text-white">
            {entry.riskScore}
          </span>
          <span className="text-xs text-slate-600">/100</span>
        </div>

        {/* Decision */}
        <span
          className={`px-2 py-0.5 rounded border text-xs font-mono w-28 text-center flex-shrink-0 ${decisionCls}`}
        >
          {entry.decision.replace("_", " ")}
        </span>

        {/* Timestamp */}
        <span className="text-xs font-mono text-slate-600 w-28 text-right flex-shrink-0 hidden lg:block">
          <Clock className="w-3 h-3 inline mr-1" />
          {formatTimestamp(entry.scannedAt)}
        </span>

        <ChevronRight
          className={`w-3.5 h-3.5 text-slate-600 flex-shrink-0 transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
        />
      </button>

      {/* Expanded row */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22 }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-4 pt-1 bg-slate-900/30 border-t border-slate-800/40">
              <div className="flex items-center gap-4 flex-wrap">
                <div>
                  <span className="text-xs text-slate-600 block mb-1">
                    Flagged By
                  </span>
                  <div className="flex gap-1.5 flex-wrap">
                    {entry.flaggedBy.length === 0 ? (
                      <span className="text-xs font-mono text-slate-500">
                        No agent flags
                      </span>
                    ) : (
                      entry.flaggedBy.map((agent) => {
                        const meta = AGENT_LABELS[agent];
                        if (!meta) return null;
                        const Icon = meta.icon;
                        return (
                          <span
                            key={agent}
                            className="flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-400"
                          >
                            <Icon className="w-3 h-3" />
                            {meta.label}
                          </span>
                        );
                      })
                    )}
                  </div>
                </div>
                <div className="ml-auto text-right">
                  <span className="text-xs text-slate-600 block mb-1">
                    Scanned
                  </span>
                  <span className="text-xs font-mono text-slate-400">
                    {formatTimestamp(entry.scannedAt)}
                  </span>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function RiskFeed() {
  const [filter, setFilter] = useState<Filter>("ALL");

  const filtered =
    filter === "ALL"
      ? MOCK_FEED
      : MOCK_FEED.filter((e) => e.riskLevel === filter);

  const counts = {
    ALL: MOCK_FEED.length,
    SAFE: MOCK_FEED.filter((e) => e.riskLevel === "SAFE").length,
    NEEDS_REVIEW: MOCK_FEED.filter((e) => e.riskLevel === "NEEDS_REVIEW").length,
    HIGH_RISK: MOCK_FEED.filter((e) => e.riskLevel === "HIGH_RISK").length,
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-slate-500" />
          <h2 className="text-base font-semibold text-white">
            Risk Operations Feed
          </h2>
          <span className="text-xs font-mono text-slate-600">
            · {MOCK_FEED.length} records
          </span>
        </div>
        <div className="text-xs font-mono text-slate-500">
          Last sync: 5s ago
        </div>
      </div>

      {/* Filter pills */}
      <div className="flex items-center gap-2 flex-wrap">
        <Filter className="w-3.5 h-3.5 text-slate-600" />
        {(["ALL", "SAFE", "NEEDS_REVIEW", "HIGH_RISK"] as Filter[]).map(
          (f) => {
            const active = filter === f;
            const label =
              f === "ALL"
                ? "All"
                : f === "NEEDS_REVIEW"
                ? "Review"
                : f === "HIGH_RISK"
                ? "High Risk"
                : "Safe";
            const activeColors =
              f === "ALL"
                ? "bg-slate-700 text-white border-slate-600"
                : f === "SAFE"
                ? "bg-emerald-900/40 text-emerald-400 border-emerald-800/50"
                : f === "NEEDS_REVIEW"
                ? "bg-amber-900/30 text-amber-400 border-amber-800/50"
                : "bg-red-900/30 text-red-400 border-red-800/50";
            return (
              <button
                key={f}
                id={`feed-filter-${f.toLowerCase()}`}
                onClick={() => setFilter(f)}
                className={`px-3 py-1 text-xs font-medium rounded-md border transition-colors ${
                  active
                    ? activeColors
                    : "bg-slate-900 text-slate-500 border-slate-800 hover:border-slate-700 hover:text-slate-400"
                }`}
              >
                {label}
                <span className="ml-1.5 opacity-60">{counts[f]}</span>
              </button>
            );
          }
        )}
      </div>

      {/* Table */}
      <div className="rounded-xl border border-slate-800 bg-surface overflow-hidden">
        {/* Column headers */}
        <div className="flex items-center gap-4 px-5 py-2 border-b border-slate-800 bg-slate-900/50">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider w-36 flex-shrink-0">
            Risk Level
          </span>
          <span className="flex-1 text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Domain
          </span>
          <span className="w-12 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider flex-shrink-0">
            Score
          </span>
          <span className="w-28 text-center text-xs font-semibold text-slate-500 uppercase tracking-wider flex-shrink-0">
            Decision
          </span>
          <span className="w-28 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider hidden lg:block flex-shrink-0">
            Timestamp
          </span>
          <span className="w-4 flex-shrink-0" />
        </div>

        <AnimatePresence mode="sync">
          {filtered.map((entry) => (
            <motion.div
              key={entry.id}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              <FeedRow entry={entry} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Approved Today", value: counts.SAFE },
          { label: "Pending Review", value: counts.NEEDS_REVIEW },
          { label: "Blocked", value: counts.HIGH_RISK },
        ].map(({ label, value }) => (
          <div
            key={label}
            className="rounded-lg border border-slate-800 bg-surface px-4 py-3"
          >
            <div className="text-2xl font-bold text-white tabular-nums">
              {value}
            </div>
            <div className="text-xs text-slate-500 mt-0.5">{label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
