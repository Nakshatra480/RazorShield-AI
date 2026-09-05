/**
 * hooks/useBenchmarkData.ts
 *
 * Fetches live benchmark results from /api/benchmark-results.
 * Falls back to MOCK_BENCHMARK values if the API route returns mock data
 * or if the fetch fails (network error, server not running, etc.).
 *
 * The returned `data` object is always in the normalized shape that the
 * benchmark components expect — no conditional rendering needed in consumers.
 */

"use client";

import { useEffect, useState } from "react";
import { MOCK_BENCHMARK } from "@/lib/mockData";

export interface BenchmarkData {
  /** Precision in percent (0–100) */
  precision: number;
  /** Recall in percent (0–100) */
  recall: number;
  /** F1-Score in percent (0–100) */
  f1Score: number;
  /** Total false-positive cost in USD */
  falsePositiveCost: number;
  /** Confusion matrix counts */
  confusionMatrix: {
    truePositive: number;
    falsePositive: number;
    trueNegative: number;
    falseNegative: number;
  };
  /** Chart data for FinancialImpactChart */
  financialImpact: Array<{
    month: string;
    traditional: number;
    razorshield: number;
  }>;
  /** ISO timestamp when benchmark was last run, or null if not yet run */
  generatedAt: string | null;
  /** True if data comes from mock fallback, false if from backend benchmark */
  isMock: boolean;
  /** Average processing time per merchant scan in milliseconds */
  avgProcessingMs: number;
  /** Total merchants evaluated */
  totalMerchants: number;
}

function normalizeLiveData(raw: Record<string, unknown>): BenchmarkData {
  const metrics = (raw.metrics ?? {}) as Record<string, number>;
  const cm = (raw.confusion_matrix ?? {}) as Record<string, number>;
  const financial = (raw.financial_impact ?? {}) as Record<string, number>;
  const chartRaw = (raw.chart_data ?? []) as Array<Record<string, unknown>>;

  // Convert chart data to the legacy format the FinancialImpactChart expects
  const financialImpact = chartRaw.map((d) => ({
    month: String(d.month_label ?? d.month ?? ""),
    // "traditional" = fraud prevented + false decline cost (what it would have cost without RazorShield)
    traditional: Number(d.fraud_prevented_usd ?? 0) + Number(d.false_declines_usd ?? 0),
    // "razorshield" = just the residual false decline cost after RazorShield
    razorshield: Number(d.false_declines_usd ?? 0),
  }));

  return {
    precision: Math.round((metrics.precision ?? 0) * 1000) / 10,       // 0.9867 → 98.7
    recall: Math.round((metrics.recall ?? 0) * 1000) / 10,
    f1Score: Math.round((metrics.f1_score ?? 0) * 1000) / 10,
    falsePositiveCost: financial.total_benchmark_cost_usd ?? 0,
    confusionMatrix: {
      truePositive: cm.true_positive ?? 0,
      falsePositive: cm.false_positive ?? 0,
      trueNegative: cm.true_negative ?? 0,
      falseNegative: cm.false_negative ?? 0,
    },
    financialImpact:
      financialImpact.length > 0 ? financialImpact : MOCK_BENCHMARK.financialImpact,
    generatedAt: (raw.generated_at as string) ?? null,
    isMock: Boolean(raw._is_mock),
    avgProcessingMs: metrics.avg_processing_ms ?? 0,
    totalMerchants: ((raw.dataset ?? {}) as Record<string, number>).total_merchants ?? 0,
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

export function useBenchmarkData(): {
  data: BenchmarkData;
  loading: boolean;
  error: string | null;
  refetch: () => void;
} {
  const [data, setData] = useState<BenchmarkData>(getMockData());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetch("/api/benchmark-results")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((raw) => {
        if (!cancelled) {
          setData(normalizeLiveData(raw as Record<string, unknown>));
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          // Silently fall back to mock — don't show error in UI
          console.warn("[useBenchmarkData] Using mock fallback:", err.message);
          setData(getMockData());
          setError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [revision]);

  return {
    data,
    loading,
    error,
    refetch: () => setRevision((r) => r + 1),
  };
}
