/**
 * components/feed/RiskFeed.tsx
 * Live feed wired to GET /api/v1/scans — reads real scan records from Postgres.
 *
 * When the backend is unreachable the feed shows an explicit empty/error state.
 * It deliberately does NOT fall back to sample rows: the previous build merged
 * MOCK_FEED entries into the live list while still showing a green "LIVE" badge,
 * so fabricated merchants appeared alongside real ones in a risk-operations
 * queue with nothing to distinguish them.
 */
"use client";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Inbox,
  RefreshCw,
  ServerCrash,
  XCircle,
} from "lucide-react";
import { getScanHistory, type ScanListItem } from "@/lib/api";
import type { FeedEntry, RiskLevel } from "@/lib/types";
import { formatRelativeTime, formatTimestamp, getRiskBg, getRiskShortLabel } from "@/lib/utils";

const RISK_ICONS = {
  SAFE: CheckCircle2,
  NEEDS_REVIEW: AlertTriangle,
  HIGH_RISK: XCircle,
} as const;

const DECISION_STYLES: Record<string, string> = {
  APPROVED: "bg-risk-safe-soft text-risk-safe border-risk-safe-border",
  MANUAL_REVIEW: "bg-risk-warn-soft text-risk-warn border-risk-warn-border",
  BLOCKED: "bg-risk-danger-soft text-risk-danger border-risk-danger-border",
};

type FilterType = "ALL" | RiskLevel;

interface FeedRow extends FeedEntry {
  fullyAnalyzed: boolean;
}

function mapScanToFeedEntry(scan: ScanListItem): FeedRow {
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
    flaggedBy: scan.guardrail_triggered ? ["GUARDRAIL"] : [],
    decision,
    fullyAnalyzed: scan.fully_analyzed ?? true,
  };
}

function Row({ entry }: { entry: FeedRow }) {
  const [expanded, setExpanded] = useState(false);
  const RiskIcon = RISK_ICONS[entry.riskLevel];

  return (
    <div className="border-b border-line last:border-0">
      <button
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="w-full flex items-center gap-4 px-5 py-3 hover:bg-surface-muted transition-colors text-left"
      >
        <span
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[11px] font-semibold w-[92px] flex-shrink-0 ${getRiskBg(
            entry.riskLevel
          )}`}
        >
          <RiskIcon className="w-3 h-3 flex-shrink-0" aria-hidden />
          {getRiskShortLabel(entry.riskLevel)}
        </span>

        <span className="flex-1 text-[13px] font-mono text-ink truncate min-w-0">
          {entry.domain}
        </span>

        {!entry.fullyAnalyzed && (
          <span
            title="This verdict was produced with one or more signals degraded"
            className="text-[10px] font-medium px-1.5 py-0.5 rounded border bg-risk-warn-soft text-risk-warn border-risk-warn-border flex-shrink-0 hidden md:inline"
          >
            degraded
          </span>
        )}

        <span className="w-11 text-right flex-shrink-0 text-[14px] font-semibold text-ink tabular-nums">
          {entry.riskScore}
        </span>

        <span
          className={`px-2 py-0.5 rounded border text-[11px] font-medium w-[104px] text-center flex-shrink-0 hidden sm:inline ${
            DECISION_STYLES[entry.decision] ?? ""
          }`}
        >
          {entry.decision.replace("_", " ").toLowerCase()}
        </span>

        <span className="text-[12px] text-ink-3 w-24 text-right flex-shrink-0 hidden lg:inline">
          {formatRelativeTime(entry.scannedAt)}
        </span>

        <ChevronRight
          className={`w-4 h-4 text-ink-4 flex-shrink-0 transition-transform ${
            expanded ? "rotate-90" : ""
          }`}
          aria-hidden
        />
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <dl className="px-5 pb-4 pt-1 bg-surface-muted/60 border-t border-line grid grid-cols-2 sm:grid-cols-4 gap-4 text-[12px]">
              <div>
                <dt className="text-ink-3 mb-0.5">Scan ID</dt>
                <dd className="font-mono text-ink-2 truncate">{entry.id.slice(0, 13)}…</dd>
              </div>
              <div>
                <dt className="text-ink-3 mb-0.5">Scanned at</dt>
                <dd className="font-mono text-ink-2">{formatTimestamp(entry.scannedAt)}</dd>
              </div>
              <div>
                <dt className="text-ink-3 mb-0.5">Guardrail</dt>
                <dd className="text-ink-2">
                  {entry.flaggedBy.length ? "Triggered" : "Not triggered"}
                </dd>
              </div>
              <div>
                <dt className="text-ink-3 mb-0.5">Analysis</dt>
                <dd className="text-ink-2">{entry.fullyAnalyzed ? "Complete" : "Degraded"}</dd>
              </div>
            </dl>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function SkeletonRow() {
  return (
    <div className="flex items-center gap-4 px-5 py-3 border-b border-line last:border-0">
      <div className="w-[92px] h-5 rounded skeleton" />
      <div className="flex-1 h-4 rounded skeleton" />
      <div className="w-11 h-5 rounded skeleton" />
      <div className="w-[104px] h-5 rounded skeleton hidden sm:block" />
      <div className="w-24 h-4 rounded skeleton hidden lg:block" />
    </div>
  );
}

export default function RiskFeed() {
  const [filter, setFilter] = useState<FilterType>("ALL");
  const [entries, setEntries] = useState<FeedRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<Date | null>(null);

  const fetchFeed = useCallback(async () => {
    try {
      const scans = await getScanHistory(100);
      setEntries(scans.map(mapScanToFeedEntry));
      setError(null);
    } catch (err) {
      setEntries([]);
      setError(err instanceof Error ? err.message : "Failed to load scan history");
    } finally {
      setLoading(false);
      setLastSync(new Date());
    }
  }, []);

  useEffect(() => {
    fetchFeed();
    const id = setInterval(fetchFeed, 30_000);
    return () => clearInterval(id);
  }, [fetchFeed]);

  const counts = useMemo(
    () => ({
      ALL: entries.length,
      SAFE: entries.filter((e) => e.riskLevel === "SAFE").length,
      NEEDS_REVIEW: entries.filter((e) => e.riskLevel === "NEEDS_REVIEW").length,
      HIGH_RISK: entries.filter((e) => e.riskLevel === "HIGH_RISK").length,
    }),
    [entries]
  );

  const filtered = filter === "ALL" ? entries : entries.filter((e) => e.riskLevel === filter);

  const FILTERS: { key: FilterType; label: string }[] = [
    { key: "ALL", label: "All" },
    { key: "SAFE", label: "Safe" },
    { key: "NEEDS_REVIEW", label: "Review" },
    { key: "HIGH_RISK", label: "High risk" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-[20px] font-semibold tracking-tight text-ink">
            Risk operations feed
          </h1>
          <p className="text-[13px] text-ink-3 mt-0.5">
            {error
              ? "Backend unreachable — showing no records rather than sample data."
              : `${entries.length} inspection${entries.length === 1 ? "" : "s"} from the database${
                  lastSync ? ` · synced ${formatRelativeTime(lastSync.toISOString())}` : ""
                }`}
          </p>
        </div>
        <button
          onClick={() => {
            setLoading(true);
            fetchFeed();
          }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium rounded-lg border border-line-strong text-ink-2 bg-surface hover:bg-surface-muted transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden />
          Refresh
        </button>
      </div>

      {/* Summary tiles */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Approved", value: counts.SAFE, tone: "text-risk-safe" },
          { label: "Pending review", value: counts.NEEDS_REVIEW, tone: "text-risk-warn" },
          { label: "Blocked", value: counts.HIGH_RISK, tone: "text-risk-danger" },
        ].map(({ label, value, tone }) => (
          <div key={label} className="rounded-xl border border-line bg-surface shadow-card px-4 py-3.5">
            <div className={`text-[26px] font-semibold tabular-nums leading-none ${tone}`}>
              {value}
            </div>
            <div className="text-[12px] text-ink-3 mt-1.5">{label}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-1.5 flex-wrap" role="tablist" aria-label="Filter by risk level">
        {FILTERS.map(({ key, label }) => {
          const active = filter === key;
          return (
            <button
              key={key}
              id={`feed-filter-${key.toLowerCase()}`}
              role="tab"
              aria-selected={active}
              onClick={() => setFilter(key)}
              className={`px-3 py-1.5 text-[12px] font-medium rounded-lg border transition-colors ${
                active
                  ? "bg-ink text-white border-ink"
                  : "bg-surface text-ink-2 border-line hover:border-line-strong"
              }`}
            >
              {label}
              <span className={`ml-1.5 tabular-nums ${active ? "opacity-70" : "text-ink-4"}`}>
                {counts[key]}
              </span>
            </button>
          );
        })}
      </div>

      {/* Table */}
      <div className="rounded-xl border border-line bg-surface shadow-card overflow-hidden">
        <div className="flex items-center gap-4 px-5 py-2.5 border-b border-line bg-surface-muted text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
          <span className="w-[92px] flex-shrink-0">Level</span>
          <span className="flex-1">Domain</span>
          <span className="w-11 text-right flex-shrink-0">Score</span>
          <span className="w-[104px] text-center flex-shrink-0 hidden sm:inline">Decision</span>
          <span className="w-24 text-right flex-shrink-0 hidden lg:inline">Scanned</span>
          <span className="w-4 flex-shrink-0" />
        </div>

        {loading ? (
          Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)
        ) : error ? (
          <div className="px-5 py-12 text-center">
            <ServerCrash className="w-7 h-7 text-ink-4 mx-auto mb-3" aria-hidden />
            <p className="text-[14px] font-medium text-ink">Cannot reach the backend</p>
            <p className="text-[13px] text-ink-3 mt-1 max-w-md mx-auto">{error}</p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="px-5 py-12 text-center">
            <Inbox className="w-7 h-7 text-ink-4 mx-auto mb-3" aria-hidden />
            <p className="text-[14px] font-medium text-ink">
              {entries.length === 0 ? "No inspections yet" : "No records match this filter"}
            </p>
            <p className="text-[13px] text-ink-3 mt-1">
              {entries.length === 0
                ? "Run a scan from the Scanner tab to populate this feed."
                : "Try a different risk level."}
            </p>
          </div>
        ) : (
          filtered.map((entry) => <Row key={entry.id} entry={entry} />)
        )}
      </div>
    </div>
  );
}
