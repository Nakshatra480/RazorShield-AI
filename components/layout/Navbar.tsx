"use client";
import React from "react";
import { motion } from "framer-motion";
import { ShieldCheck, Database, Activity } from "lucide-react";
import { useSystemHealth, type ComponentState } from "@/hooks/useSystemHealth";

type Tab = "scanner" | "feed" | "benchmark";

interface NavbarProps {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
}

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "scanner", label: "Scanner", icon: <ShieldCheck className="w-4 h-4" /> },
  { id: "feed", label: "Risk Feed", icon: <Activity className="w-4 h-4" /> },
  { id: "benchmark", label: "Benchmark", icon: <Database className="w-4 h-4" /> },
];

const STATE_DOT: Record<ComponentState, string> = {
  ok: "bg-risk-safe",
  degraded: "bg-risk-warn",
  down: "bg-risk-danger",
  unknown: "bg-ink-4",
};

const STATE_LABEL: Record<ComponentState, string> = {
  ok: "Connected",
  degraded: "Degraded",
  down: "Offline",
  unknown: "Checking…",
};

function StatusChip({
  label,
  state,
  title,
}: {
  label: string;
  state: ComponentState;
  title?: string;
}) {
  return (
    <span
      title={title ?? `${label}: ${STATE_LABEL[state]}`}
      className="flex items-center gap-1.5 text-xs text-ink-3"
    >
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${STATE_DOT[state]}`} />
      <span className="font-medium text-ink-2">{label}</span>
      <span className="text-ink-4">{STATE_LABEL[state]}</span>
    </span>
  );
}

export default function Navbar({ activeTab, onTabChange }: NavbarProps) {
  const { health } = useSystemHealth();

  return (
    <header className="fixed top-0 left-0 right-0 z-50 h-16 bg-surface border-b border-line">
      <div className="max-w-screen-xl mx-auto h-full px-4 sm:px-6 flex items-center justify-between gap-3 sm:gap-6">
        {/* Brand — wordmark collapses to the logo on narrow screens so the
            tab bar always has room instead of being clipped off-canvas. */}
        <div className="flex items-center gap-2.5 flex-shrink-0">
          <span className="w-8 h-8 rounded-lg bg-brand flex items-center justify-center flex-shrink-0">
            <ShieldCheck className="w-[18px] h-[18px] text-white" strokeWidth={2.2} />
          </span>
          <span className="hidden sm:inline text-[15px] font-semibold tracking-tight text-ink whitespace-nowrap">
            RazorShield<span className="text-brand"> AI</span>
          </span>
        </div>

        {/* Tabs */}
        <nav
          className="flex items-center gap-1 p-1 rounded-lg bg-surface-muted flex-shrink-0"
          role="tablist"
          aria-label="Sections"
        >
          {TABS.map((tab) => {
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                id={`nav-tab-${tab.id}`}
                role="tab"
                aria-selected={active}
                onClick={() => onTabChange(tab.id)}
                title={tab.label}
                className={`relative flex items-center gap-1.5 px-2.5 sm:px-3.5 py-1.5 rounded-md text-[13px] font-medium transition-colors ${
                  active ? "text-ink" : "text-ink-3 hover:text-ink-2"
                }`}
              >
                {active && (
                  <motion.span
                    layoutId="navActive"
                    className="absolute inset-0 bg-surface rounded-md shadow-card"
                    transition={{ type: "spring", duration: 0.35, bounce: 0.15 }}
                  />
                )}
                <span className="relative z-10 flex items-center gap-1.5">
                  {tab.icon}
                  {/* Label is hidden below `sm`; the icon plus title attribute
                      carries it, and aria-selected still exposes state. */}
                  <span className="hidden sm:inline whitespace-nowrap">{tab.label}</span>
                  <span className="sr-only sm:hidden">{tab.label}</span>
                </span>
              </button>
            );
          })}
        </nav>

        {/* Live dependency status — driven by GET /api/v1/readiness */}
        <div className="hidden lg:flex items-center gap-4 flex-shrink-0">
          <StatusChip label="API" state={health.backend} />
          <span className="w-px h-4 bg-line" />
          <StatusChip label="Postgres" state={health.database} />
          <span className="w-px h-4 bg-line" />
          <StatusChip
            label="LLM"
            state={health.llm}
            title={
              health.llmModel
                ? `${health.llmModel}${health.llmDetail ? ` — ${health.llmDetail}` : ""}`
                : undefined
            }
          />
        </div>
      </div>
    </header>
  );
}
