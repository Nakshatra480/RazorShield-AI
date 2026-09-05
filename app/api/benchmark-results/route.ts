/**
 * app/api/benchmark-results/route.ts
 *
 * Serves the benchmark_results.json file written by razorshield_backend/benchmark.py.
 *
 * When no benchmark has been run, this returns an EMPTY result marked
 * `_is_mock: true` rather than plausible-looking numbers. The previous version
 * returned a hand-written "realistic fallback" (precision 0.9867, recall 0.9733,
 * $328,125 fraud prevented). Those figures were indistinguishable from real
 * output in the response body, so anything that ignored the `_is_mock` flag —
 * or any screenshot of the dashboard — presented invented accuracy metrics for
 * a fraud-detection system as if they had been measured.
 *
 * GET /api/benchmark-results
 */

import { readFile } from "fs/promises";
import path from "path";
import { NextResponse } from "next/server";

const RESULTS_FILE = path.join(process.cwd(), "public", "benchmark_results.json");

/** Zeroed structure so the client can render its empty state without guards. */
const EMPTY_RESULTS = {
  generated_at: null,
  dataset: { total_merchants: 0, safe_merchants: 0, high_risk_merchants: 0 },
  metrics: {
    precision: 0,
    recall: 0,
    f1_score: 0,
    accuracy: 0,
    avg_processing_ms: 0,
  },
  confusion_matrix: {
    true_positive: 0,
    false_positive: 0,
    true_negative: 0,
    false_negative: 0,
  },
  financial_impact: {},
  cost_model: null,
  config: {},
  scan_details: [],
  _is_mock: true,
};

// Always read from disk: benchmark.py rewrites this file out of band, so a
// cached response would keep serving stale metrics after a fresh run.
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  try {
    const raw = await readFile(RESULTS_FILE, "utf-8");
    const data = JSON.parse(raw);

    // A truncated or malformed file must not be presented as a real result.
    if (!data || typeof data !== "object" || !data.metrics) {
      console.warn("[benchmark-results] Results file has no metrics block.");
      return NextResponse.json(EMPTY_RESULTS, {
        headers: { "Cache-Control": "no-store" },
      });
    }

    return NextResponse.json(
      { ...data, _is_mock: false },
      { headers: { "Cache-Control": "no-store" } }
    );
  } catch (err) {
    const code = (err as NodeJS.ErrnoException)?.code;
    if (code !== "ENOENT") {
      console.error("[benchmark-results] Failed to read results file:", err);
    }
    return NextResponse.json(EMPTY_RESULTS, {
      headers: { "Cache-Control": "no-store" },
    });
  }
}
