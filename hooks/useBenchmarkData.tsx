/**
 * hooks/useBenchmarkData.ts
 * ──────────────────────────────────────────────────────────────────────
 * Reads benchmark results from /api/benchmark-results and can trigger a fresh
 * run via POST /api/v1/benchmark/run, polling until new results land.
 *
 * `isMock` is surfaced honestly: when no benchmark has been run the UI must say
 * so rather than presenting placeholder numbers as measurements.
 */
"use client";
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { getBenchmarkStatus, runBenchmark } from "@/lib/api";

export interface CostModel {
  monthlyMerchantVolume: number;
  highRiskPrevalence: number;
  falsePositiveRate: number;
  falseNegativeRate: number;
  costPerFalsePositive: number;
  costPerFalseNegative: number;
  monthlyFalseDeclineCost: number;
  monthlyMissedFraudCost: number;
  monthlyFraudPrevented: number;
}

export interface BenchmarkData {
  precision: number;
  recall: number;
  f1Score: number;
  accuracy: number;
  confusionMatrix: {
    truePositive: number;
    falsePositive: number;
    trueNegative: number;
    falseNegative: number;
  };
  costModel: CostModel | null;
  generatedAt: string | null;
  isMock: boolean;
  avgProcessingMs: number;
  totalMerchants: number;
  /** Run provenance — replaces the hardcoded "GPT-4o / LangGraph" footer. */
  llmModel: string | null;
  embeddingModel: string | null;
  llmAvailable: boolean | null;
  randomSeed: number | null;
  degradedEvaluations: number;
}

const EMPTY: BenchmarkData = {
  precision: 0,
  recall: 0,
  f1Score: 0,
  accuracy: 0,
  confusionMatrix: {
    truePositive: 0,
    falsePositive: 0,
    trueNegative: 0,
    falseNegative: 0,
  },
  costModel: null,
  generatedAt: null,
  isMock: true,
  avgProcessingMs: 0,
  totalMerchants: 0,
  llmModel: null,
  embeddingModel: null,
  llmAvailable: null,
  randomSeed: null,
  degradedEvaluations: 0,
};

const num = (v: unknown, fallback = 0): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
};

function normalize(raw: Record<string, any>): BenchmarkData {
  const metrics = raw.metrics ?? {};
  const cm = raw.confusion_matrix ?? {};
  const model = raw.cost_model ?? null;
  const financial = raw.financial_impact ?? {};
  const config = raw.config ?? {};
  const dataset = raw.dataset ?? {};

  return {
    // Backend emits 0–1 ratios; the UI shows percentages.
    precision: Math.round(num(metrics.precision) * 1000) / 10,
    recall: Math.round(num(metrics.recall) * 1000) / 10,
    f1Score: Math.round(num(metrics.f1_score) * 1000) / 10,
    accuracy: Math.round(num(metrics.accuracy) * 1000) / 10,
    confusionMatrix: {
      truePositive: num(cm.true_positive),
      falsePositive: num(cm.false_positive),
      trueNegative: num(cm.true_negative),
      falseNegative: num(cm.false_negative),
    },
    costModel: model
      ? {
          monthlyMerchantVolume: num(model.monthly_merchant_volume, 1000),
          highRiskPrevalence: num(model.high_risk_prevalence),
          falsePositiveRate: num(model.false_positive_rate),
          falseNegativeRate: num(model.false_negative_rate),
          costPerFalsePositive: num(model.cost_per_false_positive_usd, 150),
          costPerFalseNegative: num(model.cost_per_false_negative_usd, 2500),
          monthlyFalseDeclineCost: num(model.monthly_false_decline_cost_usd),
          monthlyMissedFraudCost: num(model.monthly_missed_fraud_cost_usd),
          monthlyFraudPrevented: num(model.monthly_fraud_prevented_usd),
        }
      : // Older result files predate cost_model — derive what we can so the
        // panel still renders instead of disappearing.
        financial && Object.keys(financial).length
        ? {
            monthlyMerchantVolume: 1000,
            highRiskPrevalence: 0,
            falsePositiveRate: 0,
            falseNegativeRate: 0,
            costPerFalsePositive: num(financial.false_positive_cost_per_merchant_usd, 150),
            costPerFalseNegative: num(financial.false_negative_cost_per_merchant_usd, 2500),
            monthlyFalseDeclineCost: num(financial.monthly_false_decline_cost_usd),
            monthlyMissedFraudCost: num(financial.monthly_missed_fraud_cost_usd),
            monthlyFraudPrevented: num(financial.monthly_fraud_prevented_usd),
          }
        : null,
    generatedAt: raw.generated_at ?? null,
    isMock: Boolean(raw._is_mock),
    avgProcessingMs: num(metrics.avg_processing_ms),
    totalMerchants: num(dataset.total_merchants),
    llmModel: config.llm_model ?? null,
    embeddingModel: config.embedding_model ?? null,
    llmAvailable: typeof config.llm_available === "boolean" ? config.llm_available : null,
    randomSeed: config.random_seed ?? null,
    degradedEvaluations: num(config.degraded_evaluations),
  };
}

export type BenchmarkRunState = "idle" | "triggering" | "running" | "done" | "error";

const POLL_INTERVAL_MS = 8_000;
/** Give up polling after this long so the UI never spins forever. */
const POLL_TIMEOUT_MS = 15 * 60_000;

function useBenchmarkDataState() {
  const [data, setData] = useState<BenchmarkData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runState, setRunState] = useState<BenchmarkRunState>("idle");
  const [runMessage, setRunMessage] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollStartedRef = useRef<number>(0);
  const baselineRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const fetchResults = useCallback(async (): Promise<BenchmarkData | null> => {
    try {
      const res = await fetch("/api/benchmark-results", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = await res.json();
      const normalized = normalize(raw);
      if (!mountedRef.current) return normalized;
      setData(normalized);
      setError(null);
      return normalized;
    } catch (err) {
      if (!mountedRef.current) return null;
      const msg = err instanceof Error ? err.message : "Fetch failed";
      setError(msg);
      return null;
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    fetchResults();
    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchResults]);

  const triggerBenchmark = useCallback(async () => {
    if (runState === "triggering" || runState === "running") return;

    setRunState("triggering");
    setRunMessage("Starting benchmark…");
    baselineRef.current = data.generatedAt;

    try {
      const resp = await runBenchmark();
      setRunState("running");
      setRunMessage(resp.message ?? "Benchmark running — this takes 2–5 minutes.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to start benchmark";
      setRunState("error");
      setRunMessage(msg);
      return;
    }

    stopPolling();
    pollStartedRef.current = Date.now();

    pollRef.current = setInterval(async () => {
      if (!mountedRef.current) return stopPolling();

      // Prefer the backend's own status: it reports failures, which polling the
      // results file alone cannot distinguish from "still running".
      try {
        const status = await getBenchmarkStatus();
        if (status.status === "error") {
          stopPolling();
          setRunState("error");
          setRunMessage(status.message || "Benchmark failed.");
          return;
        }
      } catch {
        // Status endpoint unavailable — fall through to the file check.
      }

      const fresh = await fetchResults();
      if (fresh && !fresh.isMock && fresh.generatedAt !== baselineRef.current) {
        stopPolling();
        setRunState("done");
        setRunMessage(
          `Benchmark complete — ${fresh.totalMerchants} merchants evaluated.`
        );
        return;
      }

      if (Date.now() - pollStartedRef.current > POLL_TIMEOUT_MS) {
        stopPolling();
        setRunState("error");
        setRunMessage(
          "Benchmark did not report results within 15 minutes. Check the backend logs."
        );
      }
    }, POLL_INTERVAL_MS);
  }, [runState, data.generatedAt, fetchResults, stopPolling]);

  return {
    data,
    loading,
    error,
    refetch: () => {
      setLoading(true);
      fetchResults();
    },
    triggerBenchmark,
    runState,
    runMessage,
  };
}


/* ── Shared context ────────────────────────────────────────────────────────────
 *
 * MetricCards, ConfusionMatrix, FinancialImpactChart and the benchmark tab all
 * need the same results. Calling the hook in each of them meant four independent
 * fetches on mount — and, once a run was triggered, four concurrent polling
 * loops each hitting the API every 8s. They now share one instance.
 */

export type BenchmarkContextValue = ReturnType<typeof useBenchmarkDataState>;

const BenchmarkContext = createContext<BenchmarkContextValue | null>(null);

export function BenchmarkProvider({ children }: { children: React.ReactNode }) {
  const value = useBenchmarkDataState();
  return <BenchmarkContext.Provider value={value}>{children}</BenchmarkContext.Provider>;
}

export function useBenchmarkData(): BenchmarkContextValue {
  const ctx = useContext(BenchmarkContext);
  if (!ctx) {
    throw new Error("useBenchmarkData must be used inside a <BenchmarkProvider>");
  }
  return ctx;
}
