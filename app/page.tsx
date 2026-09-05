"use client";
import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Navbar from "@/components/layout/Navbar";
import ScannerHeader from "@/components/scanner/ScannerHeader";
import AgentPipeline from "@/components/scanner/AgentPipeline";
import RiskScorecard from "@/components/scanner/RiskScorecard";
import AgentAccordion from "@/components/scanner/AgentAccordion";
import AuditTrail from "@/components/scanner/AuditTrail";
import RiskFeed from "@/components/feed/RiskFeed";
import MetricCards from "@/components/benchmark/MetricCards";
import ConfusionMatrix from "@/components/benchmark/ConfusionMatrix";
import FinancialImpactChart from "@/components/benchmark/FinancialImpactChart";
import { useScanSimulation } from "@/hooks/useScanSimulation";

type Tab = "scanner" | "feed" | "benchmark";

const PAGE_TRANSITIONS = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
  transition: { duration: 0.25 },
};

export default function HomePage() {
  const [activeTab, setActiveTab] = useState<Tab>("scanner");
  const { state, startScan, reset } = useScanSimulation();

  const isScanning = state.phase === "scanning";
  const isComplete = state.phase === "complete";

  return (
    <div className="min-h-screen bg-background">
      <Navbar activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Main content — padded for navbar */}
      <main className="pt-14">
        <div className="max-w-screen-xl mx-auto px-5 py-6">
          <AnimatePresence mode="wait">
            {/* ─────────────── SCANNER ─────────────── */}
            {activeTab === "scanner" && (
              <motion.div key="scanner" {...PAGE_TRANSITIONS}>
                <div className="space-y-4">
                  {/* Hero scanner header */}
                  <ScannerHeader
                    onStartScan={startScan}
                    isScanning={isScanning}
                    onReset={reset}
                  />

                  {/* Pipeline + results only when active */}
                  {(isScanning || isComplete) && (
                    <AgentPipeline
                      agentStatuses={state.agentStatuses}
                      agentDurations={state.agentDurations}
                      progress={state.progress}
                      isScanning={isScanning}
                    />
                  )}

                  {/* Results section */}
                  <AnimatePresence>
                    {isComplete && state.result && (
                      <motion.div
                        key="results"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ duration: 0.4 }}
                        className="space-y-4"
                      >
                        <RiskScorecard result={state.result} />
                        <AgentAccordion result={state.result} />
                        <AuditTrail result={state.result} />

                        {/* New scan CTA */}
                        <div className="flex justify-center pt-2 pb-4">
                          <button
                            id="new-scan-btn"
                            onClick={reset}
                            className="px-5 py-2 text-xs font-medium text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition-colors"
                          >
                            ← Start New Scan
                          </button>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Idle state — stats preview */}
                  {state.phase === "idle" && (
                    <motion.div
                      key="idle"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-2"
                    >
                      {[
                        { label: "Merchants Scanned", value: "12,481", trend: "+148 today" },
                        { label: "Threats Blocked", value: "3,204", trend: "94.2% precision" },
                        { label: "Avg Scan Time", value: "8.2s", trend: "3 agents parallel" },
                        { label: "False Positive Rate", value: "5.8%", trend: "↓ 2.1% this week" },
                      ].map(({ label, value, trend }) => (
                        <div
                          key={label}
                          className="rounded-xl border border-slate-800 bg-surface px-4 py-4"
                        >
                          <div className="text-xl font-bold text-white tabular-nums mb-1">
                            {value}
                          </div>
                          <div className="text-xs text-slate-500">{label}</div>
                          <div className="text-xs text-blue-400/70 mt-1 font-mono">{trend}</div>
                        </div>
                      ))}
                    </motion.div>
                  )}

                  {/* Recent scans preview in idle */}
                  {state.phase === "idle" && (
                    <motion.div
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.1 }}
                      className="rounded-xl border border-slate-800 bg-surface overflow-hidden"
                    >
                      <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
                        <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
                          Recent Scans
                        </span>
                        <button
                          onClick={() => setActiveTab("feed")}
                          className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                        >
                          View all →
                        </button>
                      </div>
                      <div className="divide-y divide-slate-800/70">
                        {[
                          { domain: "techgadgets-pro.com", score: 12, level: "SAFE", time: "8 min ago" },
                          { domain: "merchant-electronics.shop", score: 78, level: "NEEDS_REVIEW", time: "32 min ago" },
                          { domain: "fastpills-rx.net", score: 97, level: "HIGH_RISK", time: "1h ago" },
                        ].map(({ domain, score, level, time }) => {
                          const colors = {
                            SAFE: "text-emerald-400 bg-emerald-900/30 border-emerald-800/50",
                            NEEDS_REVIEW: "text-amber-400 bg-amber-900/30 border-amber-800/50",
                            HIGH_RISK: "text-red-400 bg-red-900/30 border-red-800/50",
                          };
                          return (
                            <div
                              key={domain}
                              className="flex items-center gap-4 px-5 py-3 hover:bg-slate-800/30 transition-colors"
                            >
                              <span
                                className={`text-xs font-mono px-2 py-0.5 rounded border ${colors[level as keyof typeof colors]}`}
                              >
                                {level === "NEEDS_REVIEW" ? "REVIEW" : level}
                              </span>
                              <span className="flex-1 text-sm font-mono text-slate-300">{domain}</span>
                              <span className="text-sm font-bold text-white w-8 text-right">{score}</span>
                              <span className="text-xs font-mono text-slate-600 w-20 text-right">{time}</span>
                            </div>
                          );
                        })}
                      </div>
                    </motion.div>
                  )}
                </div>
              </motion.div>
            )}

            {/* ─────────────── FEED ─────────────── */}
            {activeTab === "feed" && (
              <motion.div key="feed" {...PAGE_TRANSITIONS}>
                <RiskFeed />
              </motion.div>
            )}

            {/* ─────────────── BENCHMARK ─────────────── */}
            {activeTab === "benchmark" && (
              <motion.div key="benchmark" {...PAGE_TRANSITIONS}>
                <div className="space-y-6">
                  {/* Page header */}
                  <div>
                    <h2 className="text-xl font-semibold text-white tracking-tight">
                      Benchmark & Evaluation Suite
                    </h2>
                    <p className="text-sm text-slate-500 mt-1">
                      System performance metrics evaluated on 98 labeled merchant samples.
                    </p>
                  </div>

                  <MetricCards />

                  <div className="grid lg:grid-cols-2 gap-4">
                    <ConfusionMatrix />
                    <FinancialImpactChart />
                  </div>

                  {/* Model info footer */}
                  <div className="rounded-xl border border-slate-800 bg-surface px-5 py-4">
                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
                        Evaluation Configuration
                      </span>
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      {[
                        { label: "Test Set Size", value: "98 merchants" },
                        { label: "LLM Backend", value: "GPT-4o via OpenRouter" },
                        { label: "Evaluation Date", value: "Sep 2024" },
                        { label: "Agent Framework", value: "LangGraph Multi-Agent" },
                      ].map(({ label, value }) => (
                        <div key={label}>
                          <div className="text-xs text-slate-600 mb-0.5">{label}</div>
                          <div className="text-xs font-mono text-slate-300">{value}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}
