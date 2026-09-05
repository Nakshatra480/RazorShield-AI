// Mock data for RazorShield AI — full fallback state

export type RiskLevel = "SAFE" | "NEEDS_REVIEW" | "HIGH_RISK";
export type AgentStatus = "idle" | "running" | "complete" | "error";

export interface AgentFinding {
  id: string;
  label: string;
  value: string;
  severity: "info" | "warning" | "critical";
}

export interface SubAgent {
  id: string;
  name: string;
  emoji: string;
  description: string;
  status: AgentStatus;
  durationMs: number;
  confidence: number;
  findings: AgentFinding[];
  snippet: string;
  summary: string;
}

export interface AuditStep {
  timestamp: string;
  agent: string;
  action: string;
  result: string;
  level: "info" | "warn" | "error" | "success";
}

export interface ScanResult {
  domain: string;
  url: string;
  riskScore: number;
  riskLevel: RiskLevel;
  scannedAt: string;
  totalDurationMs: number;
  keyDrivers: string[];
  agents: SubAgent[];
  auditTrail: AuditStep[];
}

export interface FeedEntry {
  id: string;
  domain: string;
  riskScore: number;
  riskLevel: RiskLevel;
  scannedAt: string;
  flaggedBy: string[];
  decision: string;
}

// ─── Mock scan result ──────────────────────────────────────────────────────────
export const MOCK_SCAN_RESULT: ScanResult = {
  domain: "merchant-electronics.shop",
  url: "https://merchant-electronics.shop",
  riskScore: 78,
  riskLevel: "NEEDS_REVIEW",
  scannedAt: "2024-09-05T09:41:22Z",
  totalDurationMs: 8240,
  keyDrivers: [
    "Domain registered < 90 days ago (42 days old) — elevated fraud signal",
    "No explicit refund policy found; partial T&C detected only",
    "1 restricted product category detected: unmarked vape accessories",
    "SSL certificate valid but issued by unverified CA (Let's Encrypt self-provisioned)",
    "WHOIS data partially redacted — registrant identity not verifiable",
  ],
  agents: [
    {
      id: "policy",
      name: "Policy Sub-Agent",
      emoji: "🛡️",
      description: "Scraping & analyzing T&C, Privacy & Refund Policy",
      status: "complete",
      durationMs: 2840,
      confidence: 81,
      summary:
        "Partial T&C detected. Refund policy missing. Privacy policy references third-party data sharing without explicit opt-out.",
      snippet: `TERMS OF SERVICE — merchant-electronics.shop
Last Updated: July 14, 2024

1. GENERAL CONDITIONS
By accessing this website you agree to be bound by these terms...

[REFUND POLICY] — NOT FOUND
[PRIVACY POLICY] — Found (partial)
  → Third-party analytics: Google Analytics, Meta Pixel
  → Data retention: unspecified
  → User opt-out: not mentioned

COMPLIANCE VERDICT: NON-COMPLIANT (score: 38/100)`,
      findings: [
        { id: "p1", label: "T&C Coverage", value: "Partial (62%)", severity: "warning" },
        { id: "p2", label: "Refund Policy", value: "Not Found", severity: "critical" },
        { id: "p3", label: "Privacy Policy", value: "Partial — missing opt-out", severity: "warning" },
        { id: "p4", label: "GDPR Compliance", value: "Non-compliant", severity: "critical" },
        { id: "p5", label: "Cookie Disclosure", value: "Present", severity: "info" },
      ],
    },
    {
      id: "catalog",
      name: "Catalog Sub-Agent",
      emoji: "📦",
      description: "Analyzing restricted products & image metadata",
      status: "complete",
      durationMs: 3120,
      confidence: 74,
      summary:
        "1 restricted category detected: vape/e-cigarette accessories listed without age verification gate. Electronics pricing is consistent with market rates.",
      snippet: `PRODUCT CATALOG SCAN — 847 SKUs analyzed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Category Distribution:
  Electronics ............. 694 items  [CLEAR]
  Phone Accessories ........ 128 items  [CLEAR]
  ⚠ Vape/E-cig Accessories .. 14 items  [FLAGGED]
  Other .................... 11 items  [CLEAR]

Flagged Items (14):
  → SKU-4421: "Vaporizer Replacement Coil x5 Pack"
  → SKU-4438: "E-Liquid Refill 30ml — Mango Ice"
  → +12 similar items

Age Verification Gate: NOT DETECTED
Restricted Sale Disclaimer: NOT FOUND`,
      findings: [
        { id: "c1", label: "Total SKUs", value: "847", severity: "info" },
        { id: "c2", label: "Restricted Items", value: "14 flagged", severity: "critical" },
        { id: "c3", label: "Age Gate", value: "Absent", severity: "critical" },
        { id: "c4", label: "Pricing Anomalies", value: "None detected", severity: "info" },
        { id: "c5", label: "Image Metadata", value: "No hidden EXIF flags", severity: "info" },
      ],
    },
    {
      id: "footprint",
      name: "Digital Footprint Sub-Agent",
      emoji: "🌐",
      description: "WHOIS, SSL, domain age & hosting analysis",
      status: "complete",
      durationMs: 2280,
      confidence: 89,
      summary:
        "Domain is 42 days old with partially redacted WHOIS data. SSL valid but self-provisioned. Hosted on shared infrastructure with moderate fraud signal cluster.",
      snippet: `WHOIS LOOKUP — merchant-electronics.shop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Registrar:    NameCheap, Inc.
Created:      2024-07-25T00:00:00Z  (42 days ago)
Updated:      2024-07-25T00:00:00Z
Expires:      2025-07-25T00:00:00Z
Registrant:   REDACTED FOR PRIVACY
Name Server:  ns1.cloudflare.com

SSL CERTIFICATE
  Issuer:     Let's Encrypt
  Valid From: 2024-07-25
  Expires:    2024-10-25
  Grade:      B (self-provisioned, no EV)

HOSTING
  IP:          104.21.48.22
  Provider:    Cloudflare, Inc.
  Country:     US
  Blacklisted: NO`,
      findings: [
        { id: "f1", label: "Domain Age", value: "42 days", severity: "critical" },
        { id: "f2", label: "WHOIS Transparency", value: "Redacted", severity: "warning" },
        { id: "f3", label: "SSL Grade", value: "B — Let's Encrypt", severity: "warning" },
        { id: "f4", label: "IP Blacklist", value: "Clean", severity: "info" },
        { id: "f5", label: "Hosting Provider", value: "Cloudflare (shared)", severity: "info" },
      ],
    },
  ],
  auditTrail: [
    {
      timestamp: "09:41:22.001",
      agent: "ORCHESTRATOR",
      action: "SCAN_INITIATED",
      result: "Target: merchant-electronics.shop | Mode: DEEP_SCAN",
      level: "info",
    },
    {
      timestamp: "09:41:22.412",
      agent: "POLICY_AGENT",
      action: "PAGE_FETCH",
      result: "Crawling /terms, /privacy, /refund — 3 endpoints resolved",
      level: "info",
    },
    {
      timestamp: "09:41:24.187",
      agent: "POLICY_AGENT",
      action: "LLM_ANALYSIS",
      result: "T&C coverage: 62% | Refund policy: NOT_FOUND | GDPR: NON_COMPLIANT",
      level: "warn",
    },
    {
      timestamp: "09:41:25.253",
      agent: "CATALOG_AGENT",
      action: "CATALOG_CRAWL",
      result: "847 SKUs indexed across 4 categories",
      level: "info",
    },
    {
      timestamp: "09:41:27.104",
      agent: "CATALOG_AGENT",
      action: "RESTRICTION_CHECK",
      result: "⚠ 14 items flagged in [VAPE/ECIG] — restricted category",
      level: "warn",
    },
    {
      timestamp: "09:41:27.890",
      agent: "CATALOG_AGENT",
      action: "AGE_GATE_CHECK",
      result: "Age verification mechanism: NOT_DETECTED",
      level: "error",
    },
    {
      timestamp: "09:41:28.301",
      agent: "FOOTPRINT_AGENT",
      action: "WHOIS_LOOKUP",
      result: "Domain age: 42 days | Registrant: REDACTED | Registrar: NameCheap",
      level: "warn",
    },
    {
      timestamp: "09:41:29.562",
      agent: "FOOTPRINT_AGENT",
      action: "SSL_INSPECT",
      result: "Certificate grade: B | Issuer: Let's Encrypt | Expires: 2024-10-25",
      level: "info",
    },
    {
      timestamp: "09:41:30.144",
      agent: "ORCHESTRATOR",
      action: "SCORE_COMPUTATION",
      result: "Risk score: 78/100 | Verdict: NEEDS_MANUAL_REVIEW",
      level: "warn",
    },
    {
      timestamp: "09:41:30.221",
      agent: "ORCHESTRATOR",
      action: "AUDIT_COMPLETE",
      result: "Report generated. Manual review required before merchant approval.",
      level: "success",
    },
  ],
};

// ─── Historical feed ───────────────────────────────────────────────────────────
export const MOCK_FEED: FeedEntry[] = [
  {
    id: "f1",
    domain: "techgadgets-pro.com",
    riskScore: 12,
    riskLevel: "SAFE",
    scannedAt: "2024-09-05T08:15:00Z",
    flaggedBy: [],
    decision: "APPROVED",
  },
  {
    id: "f2",
    domain: "merchant-electronics.shop",
    riskScore: 78,
    riskLevel: "NEEDS_REVIEW",
    scannedAt: "2024-09-05T09:41:22Z",
    flaggedBy: ["POLICY_AGENT", "CATALOG_AGENT", "FOOTPRINT_AGENT"],
    decision: "MANUAL_REVIEW",
  },
  {
    id: "f3",
    domain: "fastpills-rx.net",
    riskScore: 97,
    riskLevel: "HIGH_RISK",
    scannedAt: "2024-09-05T07:02:11Z",
    flaggedBy: ["POLICY_AGENT", "CATALOG_AGENT"],
    decision: "BLOCKED",
  },
  {
    id: "f4",
    domain: "organicwellness.store",
    riskScore: 23,
    riskLevel: "SAFE",
    scannedAt: "2024-09-04T22:18:44Z",
    flaggedBy: [],
    decision: "APPROVED",
  },
  {
    id: "f5",
    domain: "replicaluxury.shop",
    riskScore: 91,
    riskLevel: "HIGH_RISK",
    scannedAt: "2024-09-04T19:55:30Z",
    flaggedBy: ["CATALOG_AGENT", "FOOTPRINT_AGENT"],
    decision: "BLOCKED",
  },
  {
    id: "f6",
    domain: "homegarden-direct.co",
    riskScore: 18,
    riskLevel: "SAFE",
    scannedAt: "2024-09-04T17:22:00Z",
    flaggedBy: [],
    decision: "APPROVED",
  },
  {
    id: "f7",
    domain: "cryptoswap-exchange.io",
    riskScore: 84,
    riskLevel: "HIGH_RISK",
    scannedAt: "2024-09-04T14:09:18Z",
    flaggedBy: ["POLICY_AGENT", "FOOTPRINT_AGENT"],
    decision: "BLOCKED",
  },
  {
    id: "f8",
    domain: "artisan-bakery.shop",
    riskScore: 8,
    riskLevel: "SAFE",
    scannedAt: "2024-09-04T11:44:00Z",
    flaggedBy: [],
    decision: "APPROVED",
  },
  {
    id: "f9",
    domain: "discountmeds-online.biz",
    riskScore: 68,
    riskLevel: "NEEDS_REVIEW",
    scannedAt: "2024-09-04T09:31:55Z",
    flaggedBy: ["CATALOG_AGENT"],
    decision: "MANUAL_REVIEW",
  },
  {
    id: "f10",
    domain: "vintageauto-parts.net",
    riskScore: 34,
    riskLevel: "SAFE",
    scannedAt: "2024-09-03T20:15:00Z",
    flaggedBy: [],
    decision: "APPROVED",
  },
];

// ─── Benchmark metrics ─────────────────────────────────────────────────────────
export const MOCK_BENCHMARK = {
  precision: 94.2,
  recall: 91.8,
  f1Score: 92.9,
  falsePositiveCost: 120,
  confusionMatrix: {
    truePositive: 47,
    falsePositive: 3,
    trueNegative: 44,
    falseNegative: 4,
  },
  financialImpact: [
    { month: "Mar", traditional: 48000, razorshield: 8200 },
    { month: "Apr", traditional: 52000, razorshield: 7800 },
    { month: "May", traditional: 61000, razorshield: 9100 },
    { month: "Jun", traditional: 44000, razorshield: 6400 },
    { month: "Jul", traditional: 58000, razorshield: 8900 },
    { month: "Aug", traditional: 73000, razorshield: 10200 },
    { month: "Sep", traditional: 67000, razorshield: 9800 },
  ],
};
