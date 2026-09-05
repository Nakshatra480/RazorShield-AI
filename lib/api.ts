/**
 * lib/api.ts
 * ──────────────────────────────────────────────────────────────────────
 * RazorShield AI — TypeScript API client for the FastAPI backend.
 * All calls hit http://localhost:8000 (configurable via NEXT_PUBLIC_API_BASE_URL).
 */

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// ─── Shared fetch helper ───────────────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail ?? body.error ?? detail;
    } catch {
      // ignore JSON parse failure
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
}

export interface ScanListItem {
  scan_id: string;
  domain: string;
  risk_score: number;
  risk_tier: "SAFE" | "MANUAL_REVIEW" | "HIGH_RISK";
  created_at: string;
  guardrail_triggered: boolean;
}

export interface BenchmarkStatus {
  status: "running" | "complete" | "error";
  message: string;
  metrics?: Record<string, unknown>;
}

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
    false_positive_cost_usd: number;
    monthly_fraud_prevented_usd: number;
    financial_data: Array<{
      month: string;
      traditional: number;
      razorshield: number;
    }>;
  };
  dataset: {
    total_merchants: number;
    safe_merchants: number;
    high_risk_merchants: number;
  };
}

// ─── API Functions ─────────────────────────────────────────────────────────────

/**
 * POST /api/v1/inspect
 * Runs the full multi-agent inspection pipeline on a merchant URL.
 * Takes 15–60s depending on scraping + LLM latency.
 */
export async function inspectMerchant(url: string): Promise<ScanReport> {
  return apiFetch<ScanReport>("/api/v1/inspect", {
    method: "POST",
    body: JSON.stringify({ url }),
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
 * GET /api/v1/health
 * Liveness check — confirms the backend is reachable.
 */
export async function checkHealth(): Promise<boolean> {
  try {
    const data = await apiFetch<{ status: string }>("/api/v1/health");
    return data.status === "ok";
  } catch {
    return false;
  }
}
