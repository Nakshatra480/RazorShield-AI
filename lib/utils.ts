import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  return `${ms}ms`;
}

export function getRiskColor(riskLevel: string): string {
  switch (riskLevel) {
    case "SAFE":
      return "text-emerald-400";
    case "NEEDS_REVIEW":
      return "text-amber-400";
    case "HIGH_RISK":
      return "text-red-400";
    default:
      return "text-slate-400";
  }
}

export function getRiskBg(riskLevel: string): string {
  switch (riskLevel) {
    case "SAFE":
      return "bg-emerald-900/40 text-emerald-400 border-emerald-800/60";
    case "NEEDS_REVIEW":
      return "bg-amber-900/40 text-amber-400 border-amber-800/60";
    case "HIGH_RISK":
      return "bg-red-900/40 text-red-400 border-red-800/60";
    default:
      return "bg-slate-800 text-slate-400 border-slate-700";
  }
}

export function getRiskLabel(riskLevel: string): string {
  switch (riskLevel) {
    case "SAFE":
      return "SAFE";
    case "NEEDS_REVIEW":
      return "NEEDS MANUAL REVIEW";
    case "HIGH_RISK":
      return "HIGH FRAUD RISK";
    default:
      return "UNKNOWN";
  }
}

export function getScoreColor(score: number): string {
  if (score <= 35) return "#10B981";
  if (score <= 65) return "#F59E0B";
  return "#EF4444";
}

export function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
