"use client";
import React, { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ArrowLeft, Globe, Package, Shield } from "lucide-react";
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
import { useMerchantScan } from "@/hooks/useMerchantScan";
import { BenchmarkProvider, useBenchmarkData } from "@/hooks/useBenchmarkData";

type Tab = "scanner" | "feed" | "benchmark";

const PAGE_TRANSITION = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0 },
  transition: { duration: 0.2 },
};

/**
 * How the pipeline works. This is static explanatory content describing the
 * architecture, which is why it is safe to hardcode — unlike the previous idle
 * state, which hardcoded "12,481 Merchants Scanned / 3,204 Threats Blocked" and
 * a list of invented recent scans, presenting fabricated figures as live
 * operational data.
 */
const AGENT_EXPLAINERS = [
  {
    icon: Shield,
    title: "Policy compliance",
    body: "Reads the merchant's terms, privacy, refund, and contact pages and scores five required disclosures. Falls back to a deterministic rule-based scorer if the LLM is unavailable.",
    weight: "40% of score",
  },
  {
    icon: Package,
    title: "Catalog safety",
    body: "Embeds every extracted product and runs a pgvector cosine-similarity search against a seeded catalogue of prohibited goods. Any match triggers an automatic high-risk guardrail.",
    weight: "40% of score",
  },
  {
    icon: Globe,
    title: "Digital footprint",
    body: "Checks WHOIS registration age and TLS certificate validity. Domains under three days old with weak policies trigger a second guardrail.",
    weight: "20% of score",
  },
];

function ScannerTab() {
  const { state, startScan, reset } = useMerchantScan();
  const isScanning = state.phase === "scanning";
  const isComplete = state.phase === "complete";

  return (
    <div className="space-y-4">
      <ScannerHeader onStartScan={startScan} isScanning={isScanning} onReset={reset} />

      {state.phase === "error" && state.errorMessage && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          role="alert"
          className="rounded-xl border border-risk-danger-border bg-risk-danger-soft px-5 py-4 flex items-start justify-between gap-4"
        >
          <div className="flex items-start gap-3 min-w-0">
            <AlertTriangle className="w-4 h-4 text-risk-danger mt-0.5 flex-shrink-0" aria-hidden />
            <div className="min-w-0">
              <p className="text-[14px] font-semibold text-risk-danger">Inspection failed</p>
              <p className="text-[13px] text-ink-2 mt-1 break-words">{state.errorMessage}</p>
            </div>
          </div>
          <button
            onClick={reset}
            className="px-3 py-1.5 text-[12px] font-medium rounded-lg border border-risk-danger-border text-risk-danger hover:bg-white/50 transition-colors flex-shrink-0"
          >
            Dismiss
          </button>
        </motion.div>
      )}

      {(isScanning || isComplete) && (
        <AgentPipeline
          agentStatuses={state.agentStatuses}
          agentDurations={state.agentDurations}
          progress={state.progress}
          isScanning={isScanning}
        />
      )}

      <AnimatePresence>
        {isComplete && state.result && (
          <motion.div
            key="results"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.3 }}
            className="space-y-4"
          >
            <RiskScorecard result={state.result} />
            <AgentAccordion result={state.result} />
            <AuditTrail result={state.result} />

            <div className="flex justify-center pt-1 pb-2">
              <button
                id="new-scan-btn"
                onClick={reset}
                className="flex items-center gap-2 px-4 py-2 text-[13px] font-medium rounded-lg border border-line-strong text-ink-2 bg-surface hover:bg-surface-muted transition-colors"
              >
                <ArrowLeft className="w-3.5 h-3.5" aria-hidden />
                Start a new scan
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {state.phase === "idle" && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="grid md:grid-cols-3 gap-3"
        >
          {AGENT_EXPLAINERS.map(({ icon: Icon, title, body, weight }) => (
            <div key={title} className="rounded-xl border border-line bg-surface shadow-card p-5">
              <div className="flex items-center justify-between mb-3">
                <span className="w-8 h-8 rounded-lg bg-brand-soft border border-brand-border flex items-center justify-center">
                  <Icon className="w-4 h-4 text-brand" aria-hidden />
                </span>
                <span className="text-[11px] font-medium text-ink-3 px-2 py-0.5 rounded-md bg-surface-muted border border-line">
                  {weight}
                </span>
              </div>
              <h3 className="text-[14px] font-semibold text-ink">{title}</h3>
              <p className="text-[13px] text-ink-2 leading-relaxed mt-1.5">{body}</p>
            </div>
          ))}
        </motion.div>
      )}
    </div>
  );
}

function BenchmarkTabInner() {
  // Read run provenance from the results file so the footer reports the model
  // that actually produced the numbers. The previous build hardcoded
  // "GPT-4o via OpenRouter", "LangGraph Multi-Agent", "98 merchants" and
  // "Sep 2024" — none of which matched the real pipeline or dataset.
  const { data } = useBenchmarkData();

  const config: { label: string; value: string }[] = [
    {
      label: "Dataset",
      value: data.totalMerchants ? `${data.totalMerchants} labelled merchants` : "—",
    },
    { label: "LLM", value: data.llmModel ?? "—" },
    { label: "Embeddings", value: data.embeddingModel ?? "—" },
    {
      label: "Avg scan time",
      value: data.avgProcessingMs ? `${(data.avgProcessingMs / 1000).toFixed(2)}s` : "—",
    },
    { label: "Random seed", value: data.randomSeed !== null ? String(data.randomSeed) : "—" },
    {
      label: "Evaluated",
      value: data.generatedAt ? new Date(data.generatedAt).toLocaleDateString() : "—",
    },
  ];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-[20px] font-semibold tracking-tight text-ink">
          Benchmark &amp; evaluation
        </h1>
        <p className="text-[13px] text-ink-3 mt-0.5">
          Precision, recall, and error cost measured on a labelled synthetic merchant
          set. The run is seeded, so results are reproducible.
        </p>
      </div>

      <MetricCards />

      <div className="grid lg:grid-cols-2 gap-4 items-start">
        <ConfusionMatrix />
        <FinancialImpactChart />
      </div>

      <section className="rounded-xl border border-line bg-surface shadow-card px-5 py-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3 mb-3">
          Run configuration
        </h2>
        <dl className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-3">
          {config.map(({ label, value }) => (
            <div key={label} className="min-w-0">
              <dt className="text-[11px] text-ink-3 mb-0.5">{label}</dt>
              <dd className="text-[12px] font-mono text-ink-2 truncate" title={value}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
        {data.llmAvailable === false && (
          <p className="mt-3 pt-3 border-t border-line text-[12px] text-risk-warn">
            The LLM provider was unavailable during this run — policy scores came from
            the deterministic rule-based fallback.
          </p>
        )}
      </section>
    </div>
  );
}

export default function HomePage() {
  const [activeTab, setActiveTab] = useState<Tab>("scanner");

  return (
    <div className="min-h-screen bg-canvas">
      <Navbar activeTab={activeTab} onTabChange={setActiveTab} />
      <main className="pt-16">
        <div className="max-w-screen-xl mx-auto px-5 sm:px-6 py-6">
          <AnimatePresence mode="wait">
            {activeTab === "scanner" && (
              <motion.div key="scanner" {...PAGE_TRANSITION}>
                <ScannerTab />
              </motion.div>
            )}
            {activeTab === "feed" && (
              <motion.div key="feed" {...PAGE_TRANSITION}>
                <RiskFeed />
              </motion.div>
            )}
            {activeTab === "benchmark" && (
              <motion.div key="benchmark" {...PAGE_TRANSITION}>
                <BenchmarkProvider>
                  <BenchmarkTabInner />
                </BenchmarkProvider>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}
