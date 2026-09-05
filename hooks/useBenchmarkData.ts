/**
 * hooks/useBenchmarkData.ts
 * ──────────────────────────────────────────────────────────────────────
 * Fetches live benchmark results from /api/benchmark-results (Next.js route).
 * Provides `triggerBenchmark()` to fire POST /api/v1/benchmark/run on the backend
 * and then poll for updated results every 8s until a fresh result arrives.
 */

"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { MOCK_BENCHMARK } from "@/lib/mockData";
import { runBenchmark } from "@/lib/api";

export interface BenchmarkData {
  precision: number;
  recall: number;
  f1Score: number;
  falsePositiveCost: number;
  confusionMatrix: {
    truePositive: number;
    falsePositive: number;
    trueNegative: number;
    falseNegative: number;
  };
  financialImpact: Array<{ month: string; traditional: number; razorshield: number }>;
  generatedAt: string | null;
  isMock: boolean;
  avgProcessingMs: number;
  totalMerchants: number;
}

function normalizeLiveData(raw: Record<string, unknown>): BenchmarkData {
  const metrics = (raw.metrics ?? {}) as Record<string, number>;
  const cm = (raw.confusion_matrix ?? {}) as Record<string, number>;
  const financial = (raw.financial_impact ?? {}) as Record<string, unknown>;
  const chartRaw = ((financial.financial_data ?? raw.chart_data ?? []) as Array<Record<string, unknown>>);

  const financialImpact = chartRaw.map((d) => ({
    month: String(d.month_label ?? d.month ?? ""),
    traditional: Number(d.fraud_prevented_usd ?? d.traditional ?? 0) + Number(d.false_declines_usd ?? 0),
    razorshield: Number(d.false_declines_usd ?? d.razorshield ?? 0),
  }));

  return {
    precision: Math.round((metrics.precision ?? 0) * 1000) / 10,
    recall: Math.round((metrics.recall ?? 0) * 1000) / 10,
    f1Score: Math.round((metrics.f1_score ?? 0) * 1000) / 10,
    falsePositiveCost:
      ((financial as Record<string, number>).false_positive_cost_usd ??
        (financial as Record<string, number>).total_benchmark_cost_usd ??
        120),
    confusionMatrix: {
      truePositive: cm.true_positive ?? 0,
      falsePositive: cm.false_positive ?? 0,
      trueNegative: cm.true_negative ?? 0,
      falseNegative: cm.false_negative ?? 0,
    },
    financialImpact: financialImpact.length > 0 ? financialImpact : MOCK_BENCHMARK.financialImpact,
    generatedAt: (raw.generated_at as string) ?? null,
    isMock: Boolean(raw._is_mock),
    avgProcessingMs: metrics.avg_processing_ms ?? 0,
    totalMerchants: ((raw.dataset ?? {}) as Record<string, number>).total_merchants ?? 50,
  };
}

function getMockData(): BenchmarkData {
  return {
    precision: MOCK_BENCHMARK.precision,
    recall: MOCK_BENCHMARK.recall,
    f1Score: MOCK_BENCHMARK.f1Score,
    falsePositiveCost: MOCK_BENCHMARK.falsePositiveCost,
    confusionMatrix: MOCK_BENCHMARK.confusionMatrix,
    financialImpact: MOCK_BENCHMARK.financialImpact,
    generatedAt: null,
    isMock: true,
    avgProcessingMs: 3241,
    totalMerchants: 50,
  };
}

export type BenchmarkRunState = "idle" | "triggering" | "running" | "done" | "error";

export function useBenchmarkData(): {
  data: BenchmarkData;
  loading: boolean;
  error: string | null;
  refetch: () => void;
  triggerBenchmark: () => Promise<void>;
  runState: BenchmarkRunState;
  runMessage: string | null;
} {
  const [data, setData] = useState<BenchmarkData>(getMockData());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [runState, setRunState] = useState<BenchmarkRunState>("idle");
  const [runMessage, setRunMessage] = useState<string | null>(null);
  const pollRef = useRef<NodeJS.Timeout | null>(null);
  const lastGeneratedAtRef = useRef<string | null>(null);

  const fetchResults = useCallback(async (): Promise<BenchmarkData | null> => {
    try {
      const res = await fetch("/api/benchmark-results", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = await res.json();
      const normalized = normalizeLiveData(raw as Record<string, unknown>);
      setData(normalized);
      setError(null);
      return normalized;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Fetch failed";
      console.warn("[useBenchmarkData] Fallback:", msg);
      setData(getMockData());
      setError(msg);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    setLoading(true);
    fetchResults();
  }, [revision, fetchResults]);

  // Trigger the full benchmark run via the backend API, then poll for fresh results
  const triggerBenchmark = useCallback(async () => {
    if (runState === "triggering" || runState === "running") return;
    setRunState("triggering");
    setRunMessage("Sending benchmark request to backend…");

    // Snapshot the current generatedAt so we can detect when results refresh
    lastGeneratedAtRef.current = data.generatedAt;

    try {
      const resp = await runBenchmark();
      setRunState("running");
      setRunMessage(resp.message ?? "Benchmark running — this takes 2–5 minutes…");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to start benchmark";
      setRunState("error");
      setRunMessage(`Backend unreachable: ${msg}. Run manually: python3.11 -m razorshield_backend.benchmark`);
      return;
    }

    // Poll /api/benchmark-results every 8s until generatedAt changes
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      const fresh = await fetchResults();
      if (fresh && !fresh.isMock && fresh.generatedAt !== lastGeneratedAtRef.current) {
        clearInterval(pollRef.current!);
        pollRef.current = null;
        setRunState("done");
        setRunMessage(`Benchmark complete — ${fresh.totalMerchants} merchants evaluated at ${new Date(fresh.generatedAt!).toLocaleTimeString()}`);
      }
    }, 8_000);
  }, [runState, data.generatedAt, fetchResults]);

  // Clean up polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  return {
    data,
    loading,
    error,
    refetch: () => setRevision((r) => r + 1),
    triggerBenchmark,
    runState,
    runMessage,
  };
}
