/**
 * lib/api.ts
 * ──────────────────────────────────────────────────────────────────────
 * RazorShield AI — TypeScript API client for the FastAPI backend.
 * All calls hit http://localhost:8000 (configurable via NEXT_PUBLIC_API_BASE_URL).
 */

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** Default per-request ceiling. A full inspection overrides this — it scrapes + calls an LLM. */
const DEFAULT_TIMEOUT_MS = 15_000;
const INSPECT_TIMEOUT_MS = 180_000;

// ─── Shared fetch helper ───────────────────────────────────────────────────────

interface FetchOptions extends RequestInit {
  /** Abort the request after this many ms so a hung backend cannot hang the UI forever. */
  timeoutMs?: number;
}

async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal, ...init } = options;

  // Every request is time-boxed; without this a stalled fetch leaves the UI
  // stuck in "scanning" with no way back.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  if (signal) {
    signal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(init.headers ?? {}),
      },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(
        `Request timed out after ${Math.round(timeoutMs / 1000)}s — is the backend running on ${BASE_URL}?`
      );
    }
    throw new Error(
      `Cannot reach the RazorShield backend at ${BASE_URL}. Start it with: python3.11 -m uvicorn razorshield_backend.main:app --port 8000`
    );
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail ?? body.error ?? detail;
    } catch {
      // Response body was not JSON — keep the status-code message.
    }
    throw new Error(detail);
  }

  return res.json() as Promise<T>;
}

// ─── Backend Response Types ────────────────────────────────────────────────────

export interface DomainInfo {
  domain: string;
  domain_age_days: number;
  is_ssl_valid: boolean;
  ssl_expiry_days: number;
  registrar: string;
  registration_date: string | null;
}

export interface PolicyResult {
  is_compliant: boolean;
  policy_score: number;
  missing_disclosures: string[];
  /** "llm" | "heuristic" | "none" | "blocked" — which scorer produced this verdict. */
  evaluated_by?: string;
  agent_error?: string | null;
  /** True when the site blocked inspection, so policy_score is not a measurement. */
  inconclusive?: boolean;
}

export interface FlaggedItem {
  product_title: string;
  matched_category: string;
  matched_pattern: string;
  similarity_score: number;
}

export interface CatalogResult {
  has_prohibited_items: boolean;
  catalog_score: number;
  checked_via_vectors: boolean;
  flagged_items: FlaggedItem[];
  agent_error?: string | null;
}

export interface ScanReport {
  scan_id: string;
  merchant_id: string;
  domain: string;
  risk_score: number;
  risk_tier: "SAFE" | "MANUAL_REVIEW" | "HIGH_RISK";
  domain_info: DomainInfo;
  policy_result: PolicyResult;
  catalog_result: CatalogResult;
  findings: Record<string, unknown>;
  audit_trail: string;
  guardrail_triggered: boolean;
  guardrail_reason: string | null;
  processing_time_ms: number;
  created_at: string;
  /** False when any signal fell back to a degraded path. */
  fully_analyzed: boolean;
  /** True when the audit narrative was written by the LLM rather than templated. */
  llm_narrative: boolean;
}

export interface ScanListItem {
  scan_id: string;
  domain: string;
  risk_score: number;
  risk_tier: "SAFE" | "MANUAL_REVIEW" | "HIGH_RISK";
  created_at: string;
  guardrail_triggered: boolean;
  /** False when the verdict used a fallback path (LLM down, pgvector unseeded). */
  fully_analyzed?: boolean;
}

export interface BenchmarkStatus {
  status: "idle" | "running" | "complete" | "cancelled" | "error";
  message: string;
  metrics?: Record<string, unknown>;
}

/**
 * Shape written by razorshield_backend/benchmark.py.
 * The previous declaration described a `financial_impact.financial_data` array
 * that the backend never emits — the real series lives at the top level in
 * `chart_data`, which is why the chart silently fell back to mock numbers.
 */
export interface BenchmarkResults {
  generated_at: string;
  _is_mock: boolean;
  metrics: {
    precision: number;
    recall: number;
    f1_score: number;
    accuracy: number;
    avg_processing_ms: number;
  };
  confusion_matrix: {
    true_positive: number;
    false_positive: number;
    true_negative: number;
    false_negative: number;
  };
  financial_impact: {
    false_positive_cost_per_merchant_usd: number;
    false_negative_cost_per_merchant_usd: number;
    total_benchmark_cost_usd: number;
    monthly_fraud_prevented_usd: number;
    monthly_false_decline_cost_usd: number;
  };
  chart_data: Array<{
    month: number;
    month_label: string;
    fraud_prevented_usd: number;
    false_declines_usd: number;
    net_impact_usd: number;
  }>;
  dataset: {
    total_merchants: number;
    safe_merchants: number;
    high_risk_merchants: number;
  };
  scan_details: Array<{
    url: string;
    true_label: string;
    predicted: string;
    risk_score: number;
    correct: boolean;
    guardrail: boolean;
    processing_ms: number;
  }>;
  config?: {
    llm_model?: string;
    embedding_model?: string;
    llm_available?: boolean;
    random_seed?: number;
  };
}

/** GET /api/v1/readiness — real dependency status, used by the header. */
export interface ReadinessReport {
  status: "ok" | "degraded";
  service: string;
  version: string;
  components: {
    database?: { status: string; detail?: string; latency_ms?: number };
    browser?: { status: string; detail?: string };
    llm?: { status: string; model?: string; detail?: string };
  };
}

// ─── API Functions ─────────────────────────────────────────────────────────────

/**
 * POST /api/v1/inspect
 * Runs the full multi-agent inspection pipeline on a merchant URL.
 * Takes 15–60s depending on scraping + LLM latency.
 */
export async function inspectMerchant(
  url: string,
  signal?: AbortSignal
): Promise<ScanReport> {
  return apiFetch<ScanReport>("/api/v1/inspect", {
    method: "POST",
    body: JSON.stringify({ url }),
    timeoutMs: INSPECT_TIMEOUT_MS,
    signal,
  });
}

/**
 * POST /api/v1/benchmark/run
 * Fires the 50-merchant synthetic benchmark in the background.
 * Returns immediately; results land in /api/benchmark-results.
 */
export async function runBenchmark(): Promise<BenchmarkStatus> {
  return apiFetch<BenchmarkStatus>("/api/v1/benchmark/run", {
    method: "POST",
  });
}

/**
 * GET /api/v1/scans
 * Fetches paginated list of past inspections from Neon PostgreSQL.
 */
export async function getScanHistory(
  limit = 50,
  offset = 0
): Promise<ScanListItem[]> {
  return apiFetch<ScanListItem[]>(
    `/api/v1/scans?limit=${limit}&offset=${offset}`
  );
}

/**
 * GET /api/v1/scans/:id
 * Retrieves a single full scan report by UUID.
 */
export async function getScanById(scanId: string): Promise<ScanReport> {
  return apiFetch<ScanReport>(`/api/v1/scans/${scanId}`);
}

/**
 * GET /api/benchmark-results (Next.js internal route)
 * Reads the latest benchmark_results.json written by benchmark.py.
 */
export async function getBenchmarkResults(): Promise<BenchmarkResults> {
  const res = await fetch("/api/benchmark-results", { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load benchmark results");
  return res.json();
}

/**
 * GET /api/v1/benchmark/status
 * Reports the state of the most recent background benchmark run, so the UI can
 * distinguish "still running" from "failed" while polling.
 */
export async function getBenchmarkStatus(): Promise<BenchmarkStatus> {
  return apiFetch<BenchmarkStatus>("/api/v1/benchmark/status", { timeoutMs: 8_000 });
}

/**
 * GET /api/v1/health
 * Liveness check — confirms the backend process is reachable.
 */
export async function checkHealth(): Promise<boolean> {
  try {
    const data = await apiFetch<{ status: string }>("/api/v1/health", {
      timeoutMs: 5_000,
    });
    return data.status === "ok";
  } catch {
    return false;
  }
}

/**
 * GET /api/v1/readiness
 * Dependency check — reports live status of Postgres, Playwright, and the LLM
 * provider so the UI can show real state rather than decorative badges.
 */
export async function getReadiness(): Promise<ReadinessReport> {
  return apiFetch<ReadinessReport>("/api/v1/readiness", { timeoutMs: 8_000 });
}
