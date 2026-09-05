# RazorShield AI 🛡️

### Autonomous Multi-Agent Merchant Risk Inspector

**Razorpay AI Builder Internship — Track 2: AI Risk Manager**

---

## What It Does

RazorShield AI is a production-ready autonomous pipeline that inspects any merchant website and produces a structured risk verdict — combining three independent signals into a single weighted score (0–100) in under 20 seconds.

You give it a URL. It scrapes the site, reads the legal pages, checks what they're selling, and verifies the domain. Three agents run in parallel. One score comes back with the full evidence behind it.

| Agent | What it checks | How |
|---|---|---|
| **Policy Agent** | Legal compliance | LLM reads T&C, Privacy, Refund, Contact pages; falls back to rule-based scorer if LLM is unavailable |
| **Catalog Agent** | Prohibited goods | Local sentence-transformer embeddings + pgvector cosine similarity against 30 banned-item categories |
| **Footprint Agent** | Domain fraud signals | WHOIS registration age + TLS certificate validity |

---

## Architecture

```
  Analyst enters URL
         │
         ▼
┌─────────────────┐     HTTP/JSON     ┌──────────────────────────┐
│  Next.js 14 UI  │ ◄────────────── ► │  FastAPI Backend          │
│  (port 3000)    │                   │  (port 8000)              │
└─────────────────┘                   └───────────┬──────────────┘
                                                  │
                                    ┌─────────────▼──────────────┐
                                    │   Playwright Scraper        │
                                    │   Headless Chromium         │
                                    │   homepage · /terms ·       │
                                    │   /privacy · /products      │
                                    └─────────────┬──────────────┘
                                                  │
                                    ┌─────────────▼──────────────┐
                                    │   Orchestrator              │
                                    │   asyncio.gather()          │
                                    └──┬──────────┬──────────┬───┘
                                       │          │          │
                              ┌────────▼──┐ ┌─────▼────┐ ┌──▼──────────┐
                              │  Policy   │ │ Catalog  │ │  Footprint  │
                              │  Agent    │ │  Agent   │ │   Agent     │
                              │ LiteLLM   │ │pgvector  │ │ WHOIS + SSL │
                              │ Llama-70b │ │ 768-dim  │ │             │
                              └─────┬─────┘ └────┬─────┘ └──────┬──────┘
                                    └────────────┼──────────────┘
                                                 │
                                    ┌────────────▼──────────────┐
                                    │   Risk Score Engine        │
                                    │   Weighted score 0–100     │
                                    │   + Guardrail overrides    │
                                    │   + Audit narrative        │
                                    └────────────┬──────────────┘
                                                 │
                                    ┌────────────▼──────────────┐
                                    │   Neon PostgreSQL          │
                                    │   + pgvector extension     │
                                    │   merchants · scans ·      │
                                    │   prohibited_patterns      │
                                    └────────────────────────────┘
```

### Scoring Logic

```
Guardrail A: domain_age < 3 days AND policy_score < 0.4  →  HIGH_RISK (score 95)
Guardrail B: has_prohibited_items = True                  →  HIGH_RISK (score 90)

Composite (when no guardrail fires):
  0.4 × (100 − policy_score×100)
+ 0.4 × (100 − catalog_score×100)
+ 0.2 × domain_risk_component

Risk tiers:
   0 –  34  →  SAFE
  35 –  64  →  MANUAL_REVIEW
  65 – 100  →  HIGH_RISK
```

---

## Tech Stack

**Frontend** — Next.js 14 · TypeScript · Tailwind CSS · Framer Motion · Recharts  
**Backend** — Python 3.11 · FastAPI · Playwright · LiteLLM → OpenRouter · SentenceTransformers  
**Database** — Neon PostgreSQL · pgvector (768-dim cosine similarity) · SQLAlchemy 2 async  
**Testing** — pytest · pytest-asyncio · pytest-timeout · 30+ tests across 6 modules

---

## Quick Start

### Prerequisites

- Python 3.11 (`brew install python@3.11`)
- Node.js 18+ (`brew install node`)
- Neon PostgreSQL account with pgvector enabled (free tier works)
- OpenRouter API key (free tier works)

### 1. Clone & configure

```bash
git clone https://github.com/Nakshatra480/RazorShield-AI.git
cd RazorShield-AI

cp .env.example .env
# Edit .env and fill in OPENROUTER_API_KEY and DATABASE_URL
```

### 2. Install backend dependencies

```bash
bash razorshield_backend/setup.sh
```

Installs PyTorch (CPU-only), SentenceTransformers, Playwright Chromium, and all Python packages.

### 3. Install frontend dependencies

```bash
npm install
```

### 4. One-command launch

```bash
bash start.sh
```

Starts both servers concurrently with graceful shutdown on Ctrl-C:

- **Frontend:** http://localhost:3000
- **Backend:** http://localhost:8000
- **API Docs:** http://localhost:8000/api/docs

### 5. Manual launch (alternative)

```bash
# Terminal 1 — Backend
python3.11 -m uvicorn razorshield_backend.main:app --port 8000

# Terminal 2 — Frontend
npm run dev
```

---

## Running the Benchmark

Evaluates the full scoring pipeline against 50 programmatically-generated synthetic merchant profiles (35 safe, 15 high-risk). No live scraping — runs entirely offline using injected synthetic data.

```bash
python3.11 -m razorshield_backend.benchmark
```

Results are written to `public/benchmark_results.json` and displayed automatically in the **Benchmark & Metrics** tab of the UI. You can also trigger it from the UI using the **Run Benchmark Suite** button.

---

## Running Tests

```bash
# Run all tests (excludes slow benchmark subprocess tests)
python3.11 -m pytest tests/ -v --tb=short -m "not slow"

# Run a specific module
python3.11 -m pytest tests/test_api.py -v
```

The backend must be running on port 8000 for `test_api.py`.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Liveness probe |
| `GET` | `/api/v1/readiness` | Dependency health (DB, browser, LLM) |
| `POST` | `/api/v1/inspect` | Run full merchant inspection |
| `GET` | `/api/v1/scans` | List past scans (paginated) |
| `GET` | `/api/v1/scans/{id}` | Get single scan by UUID |
| `POST` | `/api/v1/benchmark/run` | Trigger benchmark evaluation |
| `GET` | `/api/v1/benchmark/status` | Benchmark progress |

Full interactive docs: **http://localhost:8000/api/docs**

### Example

```bash
# Inspect a live merchant
curl -X POST http://localhost:8000/api/v1/inspect \
  -H "Content-Type: application/json" \
  -d '{"url": "https://stripe.com"}'

# Health check
curl http://localhost:8000/api/v1/health

# List past scans
curl "http://localhost:8000/api/v1/scans?limit=10"
```

---

## Project Structure

```
RazorShield-AI/
├── app/                              # Next.js 14 App Router
│   ├── page.tsx                      # Main dashboard (Scanner / Feed / Benchmark tabs)
│   ├── layout.tsx                    # Root layout + fonts
│   ├── globals.css                   # Tailwind + design tokens
│   └── api/benchmark-results/        # Next.js API route serving benchmark JSON
├── components/
│   ├── scanner/                      # ScannerHeader, AgentPipeline, RiskScorecard,
│   │                                 # AgentAccordion, AuditTrail
│   ├── benchmark/                    # MetricCards, ConfusionMatrix, FinancialImpactChart
│   ├── feed/                         # RiskFeed (live DB data, real-time polling)
│   └── layout/                       # Navbar with system health status chips
├── hooks/
│   ├── useMerchantScan.ts            # Real API calls to POST /api/v1/inspect
│   ├── useBenchmarkData.tsx          # Benchmark context + triggerBenchmark()
│   └── useSystemHealth.ts            # Polls /api/v1/readiness every 30s
├── lib/
│   ├── api.ts                        # TypeScript API client
│   ├── types.ts                      # View-model type definitions
│   └── utils.ts                      # Formatting + risk-tier helpers
├── razorshield_backend/
│   ├── main.py                       # FastAPI app + all endpoints
│   ├── config.py                     # Pydantic settings (env vars, lru_cache)
│   ├── benchmark.py                  # 50-merchant synthetic evaluation harness
│   ├── agents/
│   │   ├── orchestrator.py           # asyncio.gather() multi-agent runner + scoring
│   │   ├── llm.py                    # Shared LLM transport: timeouts, retries, circuit breaker
│   │   ├── policy_agent.py           # LLM compliance checker + rule-based fallback
│   │   └── catalog_agent.py          # Batched pgvector similarity search (thread-safe)
│   ├── scrapers/
│   │   ├── browser.py                # Loop-aware Playwright singleton manager
│   │   └── whois_client.py           # WHOIS + TLS inspector (time-bounded)
│   ├── db/
│   │   ├── database.py               # SQLAlchemy async engine + pgvector init
│   │   └── models.py                 # Merchant, Scan, ProhibitedPattern ORM models
│   ├── requirements.txt              # Python dependencies
│   └── setup.sh                      # macOS setup script (PyTorch CPU + Playwright)
├── tests/
│   ├── conftest.py                   # Fixtures: DB session, scrape results
│   ├── test_db.py                    # Database + pgvector layer (4 tests)
│   ├── test_scrapers.py              # Playwright + WHOIS/SSL scraper (4 tests)
│   ├── test_agents.py                # Policy, Catalog, Orchestrator agents (7 tests)
│   ├── test_api.py                   # FastAPI endpoint integration (5 tests)
│   ├── test_benchmark.py             # Benchmark results validation (9 tests)
│   └── test_config.py                # Settings + env validation (3 tests)
├── public/
│   ├── benchmark_results.json        # Pre-computed benchmark (100% P/R/F1 on 50 merchants)
│   └── preview.png                   # UI screenshot
├── start.sh                          # One-command concurrent launcher
├── pytest.ini                        # pytest configuration
└── .env.example                      # Environment variable template
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
# LLM — OpenRouter
OPENROUTER_API_KEY=sk-or-v1-your_key_here
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openrouter/meta-llama/llama-3.1-70b-instruct
LLM_TIMEOUT_SECONDS=30
LLM_MAX_ATTEMPTS=3

# Database — Neon PostgreSQL with pgvector
DATABASE_URL=postgresql://user:password@ep-xxx.neon.tech/neondb?sslmode=require
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10

# Embeddings — local BAAI/bge-base-en-v1.5 (~400MB download on first run)
EMBEDDING_MODEL_NAME=BAAI/bge-base-en-v1.5
EMBEDDING_DIMENSIONS=768
PROHIBITED_SIMILARITY_THRESHOLD=0.75

# Limits
MAX_CONCURRENT_INSPECTIONS=5
MAX_PRODUCTS_PER_SCAN=20
INSPECTION_TIMEOUT_SECONDS=180

# CORS
CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:3001
ENVIRONMENT=development
```

---

## Benchmark Results

Evaluated on 50 synthetic merchant profiles (35 safe · 15 high-risk), Sep 2026:

| Metric | Score |
|---|---|
| Precision | **100.0%** |
| Recall | **100.0%** |
| F1-Score | **100.0%** |
| Avg processing time | ~14 000 ms/merchant |
| Guardrail activations | 15 / 15 high-risk merchants |

**Confusion Matrix:**

```
                  Predicted SAFE   Predicted HIGH_RISK
Actual SAFE            35                  0
Actual HIGH_RISK        0                 15
```

The benchmark uses a fixed random seed (`20240915`) so results are reproducible. Every run on the same codebase produces the same 50 merchants.

---

## Design Decisions

**Why a rule-based fallback for the Policy Agent?**  
When the LLM provider is unavailable, returning `policy_score=0.0` is wrong in both directions — a fully compliant merchant gets pushed toward HIGH_RISK. The rule-based scorer checks the same five rubric items deterministically and keeps the 40% signal meaningful when the API is down. The `evaluated_by` field on every result tells you which path ran.

**Why pgvector over keyword matching?**  
Keyword lists miss paraphrasing. A product listed as "oxy 80mg, no prescription needed" contains none of the words in a typical blocklist but is semantically close to "opioid controlled substance" in the embedding space. pgvector catches it; keyword matching doesn't.

**Why asyncio.gather() for the three agents?**  
Each agent has independent I/O — LLM call, vector DB query, WHOIS lookup. Running them concurrently cuts the per-scan wall time by roughly 2× compared to running them in sequence.

**Why a semaphore on the inspect endpoint?**  
Each inspection holds a browser context, an embedding batch, and a database connection. Without a concurrency ceiling a burst of traffic exhausts the DB pool. `max_concurrent_inspections` (default 5) bounds this cleanly.

---

## License

MIT © 2026 Nakshatra Sharma
