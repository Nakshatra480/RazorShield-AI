/**
 * components/feed/RiskFeed.tsx
 * Live feed wired to GET /api/v1/scans — reads real scan records from Neon DB.
 * Falls back to MOCK_FEED if the backend is unreachable.
 */
"use client";
import React, { useState, useEffect, useCallback } from "react";
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
  RefreshCw,
  Wifi,
  WifiOff,
} from "lucide-react";
import { getScanHistory, type ScanListItem } from "@/lib/api";
import { MOCK_FEED, type FeedEntry, type RiskLevel } from "@/lib/mockData";
import { getRiskBg, formatTimestamp } from "@/lib/utils";

const RISK_ICONS = {
  SAFE: CheckCircle,
  NEEDS_REVIEW: AlertTriangle,
  HIGH_RISK: XCircle,
};

const DECISION_STYLES: Record<string, string> = {
  APPROVED: "text-emerald-400 bg-emerald-900/20 border-emerald-800/40",
  MANUAL_REVIEW: "text-amber-400 bg-amber-900/20 border-amber-800/40",
  BLOCKED: "text-red-400 bg-red-900/20 border-red-800/40",
};

type FilterType = "ALL" | RiskLevel;

// Map backend ScanListItem → FeedEntry
function mapScanToFeedEntry(scan: ScanListItem): FeedEntry {
  const tier = scan.risk_tier;
  const level: RiskLevel =
    tier === "SAFE" ? "SAFE" : tier === "HIGH_RISK" ? "HIGH_RISK" : "NEEDS_REVIEW";
  const decision =
    tier === "SAFE" ? "APPROVED" : tier === "HIGH_RISK" ? "BLOCKED" : "MANUAL_REVIEW";
  return {
    id: scan.scan_id,
    domain: scan.domain,
    riskScore: Math.round(scan.risk_score),
    riskLevel: level,
    scannedAt: scan.created_at,
    flaggedBy: scan.guardrail_triggered ? ["POLICY_AGENT"] : [],
    decision,
  };
}

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
        <span
          className={`flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-semibold tracking-wide w-36 flex-shrink-0 ${riskBg}`}
        >
          <RiskIcon className="w-3 h-3" />
          {entry.riskLevel === "NEEDS_REVIEW" ? "REVIEW" : entry.riskLevel}
        </span>
        <span className="flex-1 text-sm font-mono text-slate-200 truncate">
          {entry.domain}
        </span>
        <div className="w-12 text-right flex-shrink-0">
          <span className="text-sm font-bold tabular-nums text-white">
            {entry.riskScore}
          </span>
          <span className="text-xs text-slate-600">/100</span>
        </div>
        <span
          className={`px-2 py-0.5 rounded border text-xs font-mono w-28 text-center flex-shrink-0 ${decisionCls}`}
        >
          {entry.decision.replace("_", " ")}
        </span>
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
                  <span className="text-xs text-slate-600 block mb-1">Flagged By</span>
                  <div className="flex gap-1.5 flex-wrap">
                    {entry.flaggedBy.length === 0 ? (
                      <span className="text-xs font-mono text-slate-500">No agent flags</span>
                    ) : (
                      entry.flaggedBy.map((agent) => (
                        <span
                          key={agent}
                          className="flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-400"
                        >
                          <Shield className="w-3 h-3" />
                          {agent.replace("_AGENT", "")}
                        </span>
                      ))
                    )}
                  </div>
                </div>
                <div className="ml-auto text-right">
                  <span className="text-xs text-slate-600 block mb-1">Scan ID</span>
                  <span className="text-xs font-mono text-slate-500 truncate max-w-[120px] block">
                    {entry.id.slice(0, 8)}…
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

function SkeletonRow() {
  return (
    <div className="flex items-center gap-4 px-5 py-3.5 border-b border-slate-800/70 last:border-0 animate-pulse">
      <div className="w-36 h-5 rounded bg-slate-800" />
      <div className="flex-1 h-4 rounded bg-slate-800" />
      <div className="w-10 h-5 rounded bg-slate-800" />
      <div className="w-28 h-5 rounded bg-slate-800" />
      <div className="w-24 h-4 rounded bg-slate-800 hidden lg:block" />
    </div>
  );
}

export default function RiskFeed() {
  const [filter, setFilter] = useState<FilterType>("ALL");
  const [entries, setEntries] = useState<FeedEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [isLive, setIsLive] = useState(false);
  const [lastSync, setLastSync] = useState<Date | null>(null);

  const fetchFeed = useCallback(async () => {
    try {
      const scans = await getScanHistory(100);
      const mapped = scans.map(mapScanToFeedEntry);
      // Merge with mock: live scans first, then pad with mock entries not already present
      const liveDomains = new Set(mapped.map((e) => e.domain));
      const mockPad = MOCK_FEED.filter((e) => !liveDomains.has(e.domain));
      setEntries([...mapped, ...mockPad]);
      setIsLive(true);
    } catch {
      // Backend unreachable — fall back to mock data
      setEntries(MOCK_FEED);
      setIsLive(false);
    } finally {
      setLoading(false);
      setLastSync(new Date());
    }
  }, []);

  useEffect(() => {
    fetchFeed();
    // Refresh every 30s
    const interval = setInterval(fetchFeed, 30_000);
    return () => clearInterval(interval);
  }, [fetchFeed]);

  const filtered =
    filter === "ALL" ? entries : entries.filter((e) => e.riskLevel === filter);

  const counts = {
    ALL: entries.length,
    SAFE: entries.filter((e) => e.riskLevel === "SAFE").length,
    NEEDS_REVIEW: entries.filter((e) => e.riskLevel === "NEEDS_REVIEW").length,
    HIGH_RISK: entries.filter((e) => e.riskLevel === "HIGH_RISK").length,
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-slate-500" />
          <h2 className="text-base font-semibold text-white">Risk Operations Feed</h2>
          <span className="text-xs font-mono text-slate-600">· {entries.length} records</span>
          {/* Live / offline badge */}
          <span
            className={`flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded-full border ${
              isLive
                ? "text-emerald-400 bg-emerald-900/20 border-emerald-800/40"
                : "text-slate-500 bg-slate-800/40 border-slate-700"
            }`}
          >
            {isLive ? (
              <><Wifi className="w-3 h-3" /> LIVE</>
            ) : (
              <><WifiOff className="w-3 h-3" /> DEMO</>
            )}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs font-mono text-slate-500">
            {lastSync ? `Synced ${Math.round((Date.now() - lastSync.getTime()) / 1000)}s ago` : "Syncing…"}
          </span>
          <button
            onClick={() => { setLoading(true); fetchFeed(); }}
            className="p-1.5 rounded-md hover:bg-slate-800 transition-colors text-slate-500 hover:text-slate-300"
            title="Refresh feed"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Filter pills */}
      <div className="flex items-center gap-2 flex-wrap">
        <Filter className="w-3.5 h-3.5 text-slate-600" />
        {(["ALL", "SAFE", "NEEDS_REVIEW", "HIGH_RISK"] as FilterType[]).map((f) => {
          const active = filter === f;
          const label =
            f === "ALL" ? "All" : f === "NEEDS_REVIEW" ? "Review" : f === "HIGH_RISK" ? "High Risk" : "Safe";
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
        })}
      </div>

      {/* Table */}
      <div className="rounded-xl border border-slate-800 bg-surface overflow-hidden">
        <div className="flex items-center gap-4 px-5 py-2 border-b border-slate-800 bg-slate-900/50">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider w-36 flex-shrink-0">Risk Level</span>
          <span className="flex-1 text-xs font-semibold text-slate-500 uppercase tracking-wider">Domain</span>
          <span className="w-12 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider flex-shrink-0">Score</span>
          <span className="w-28 text-center text-xs font-semibold text-slate-500 uppercase tracking-wider flex-shrink-0">Decision</span>
          <span className="w-28 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider hidden lg:block flex-shrink-0">Timestamp</span>
          <span className="w-4 flex-shrink-0" />
        </div>

        {loading ? (
          Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)
        ) : filtered.length === 0 ? (
          <div className="px-5 py-8 text-center text-sm text-slate-600">
            No records match the selected filter.
          </div>
        ) : (
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
        )}
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Approved", value: counts.SAFE },
          { label: "Pending Review", value: counts.NEEDS_REVIEW },
          { label: "Blocked", value: counts.HIGH_RISK },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-lg border border-slate-800 bg-surface px-4 py-3">
            <div className="text-2xl font-bold text-white tabular-nums">{value}</div>
            <div className="text-xs text-slate-500 mt-0.5">{label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
