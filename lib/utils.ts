import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  return `${Math.round(ms)}ms`;
}

/**
 * Format a USD amount.
 *
 * Amounts below $10,000 are shown exactly. Abbreviating earlier turned unit
 * costs into wrong numbers — a $2,500 chargeback assumption rendered as "$3K",
 * which misstates a figure the reader is meant to check the model against.
 * Only large aggregates, where a rounded magnitude is the point, get K/M.
 */
export function formatUsd(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";

  if (abs >= 1_000_000) {
    return `${sign}$${(abs / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  }
  if (abs >= 10_000) {
    return `${sign}$${Math.round(abs / 1_000)}K`;
  }
  return `${sign}$${Math.round(abs).toLocaleString("en-US")}`;
}

/* ── Risk semantics ───────────────────────────────────────────────────────── */

export type RiskLevelKey = "SAFE" | "NEEDS_REVIEW" | "HIGH_RISK";

/** Text-only colour, for numbers and inline emphasis. */
export function getRiskColor(riskLevel: string): string {
  switch (riskLevel) {
    case "SAFE":
      return "text-risk-safe";
    case "NEEDS_REVIEW":
      return "text-risk-warn";
    case "HIGH_RISK":
      return "text-risk-danger";
    default:
      return "text-ink-3";
  }
}

/**
 * Badge styling. Light theme uses a tinted fill with a matching border and the
 * saturated hue reserved for text, which keeps contrast above 4.5:1 while
 * letting several badges sit next to each other without vibrating.
 */
export function getRiskBg(riskLevel: string): string {
  switch (riskLevel) {
    case "SAFE":
      return "bg-risk-safe-soft text-risk-safe border-risk-safe-border";
    case "NEEDS_REVIEW":
      return "bg-risk-warn-soft text-risk-warn border-risk-warn-border";
    case "HIGH_RISK":
      return "bg-risk-danger-soft text-risk-danger border-risk-danger-border";
    default:
      return "bg-surface-muted text-ink-3 border-line";
  }
}

export function getRiskLabel(riskLevel: string): string {
  switch (riskLevel) {
    case "SAFE":
      return "Safe to onboard";
    case "NEEDS_REVIEW":
      return "Needs manual review";
    case "HIGH_RISK":
      return "High fraud risk";
    default:
      return "Unknown";
  }
}

/** Short label for dense tables where the full phrase will not fit. */
export function getRiskShortLabel(riskLevel: string): string {
  switch (riskLevel) {
    case "SAFE":
      return "Safe";
    case "NEEDS_REVIEW":
      return "Review";
    case "HIGH_RISK":
      return "High risk";
    default:
      return "Unknown";
  }
}

/** Hex values for SVG/canvas surfaces that cannot take a Tailwind class. */
export function getScoreColor(score: number): string {
  if (score < 35) return "#0F8A5F"; // risk.safe
  if (score < 65) return "#B26A00"; // risk.warn
  return "#D0342C"; // risk.danger
}

/**
 * Tier thresholds mirror the backend exactly (orchestrator._determine_tier):
 * <35 SAFE, <65 MANUAL_REVIEW, else HIGH_RISK.
 */
export function scoreToRiskLevel(score: number): RiskLevelKey {
  if (score < 35) return "SAFE";
  if (score < 65) return "NEEDS_REVIEW";
  return "HIGH_RISK";
}

export function getSeverityBadge(severity: string): string {
  switch (severity) {
    case "critical":
      return "bg-risk-danger-soft text-risk-danger border-risk-danger-border";
    case "warning":
      return "bg-risk-warn-soft text-risk-warn border-risk-warn-border";
    default:
      return "bg-brand-soft text-brand-ink border-brand-border";
  }
}

/* ── Time ─────────────────────────────────────────────────────────────────── */

export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatTimestamp(iso);
}

/* ── Shared surface classes ───────────────────────────────────────────────── */

export const CARD = "rounded-xl border border-line bg-surface shadow-card";
export const SECTION_LABEL =
  "text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3";
