# RazorShield AI 🛡️
### Autonomous Multi-Agent Merchant Risk & Onboarding Inspector
**Razorpay AI Builder Internship — Track 2: AI Risk Manager**

---

## What It Does

RazorShield AI is a production-ready autonomous pipeline that scrapes any merchant website and produces a structured risk verdict in under 60 seconds — combining three orthogonal signals into a single weighted score (0–100):

| Agent | Signal | Method |
|---|---|---|
| **Policy Sub-Agent** | Legal compliance | LLM reads T&C, Privacy, Refund pages |
| **Catalog Sub-Agent** | Prohibited goods | pgvector cosine similarity search |
| **Digital Footprint Sub-Agent** | Domain fraud signals | WHOIS + SSL + domain age |

---

## Architecture

```
  Analyst enters URL
         │
         ▼
┌─────────────────┐     HTTP/JSON     ┌──────────────────────────┐
│  Next.js 14 UI  │ ◄────────────── ► │  FastAPI Backend          │
│  (port 3001)    │                   │  (port 8000)              │
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
                              │ Sub-Agent │ │Sub-Agent │ │  Sub-Agent  │
                              │ LiteLLM   │ │pgvector  │ │ WHOIS + SSL │
                              │ llama-70b │ │768-dim   │ │             │
                              └─────┬─────┘ └────┬─────┘ └──────┬──────┘
                                    └────────────┼──────────────┘
                                                 │
                                    ┌────────────▼──────────────┐
                                    │   Risk Score Engine        │
                                    │   Weighted score 0–100     │
                                    │   + Guardrail overrides    │
                                    │   + LLM Audit Narrative    │
                                    └────────────┬──────────────┘
                                                 │
                                    ┌────────────▼──────────────┐
                                    │   Neon PostgreSQL          │
                                    │   + pgvector extension     │
                                    │   merchants · scans ·      │
                                    │   prohibited_patterns      │
                                    └────────────────────────────┘
```

---

## Tech Stack

**Frontend** — Next.js 14 · TypeScript · Tailwind CSS · Framer Motion · Three.js · Recharts  
**Backend** — Python 3.11 · FastAPI · Playwright · LiteLLM → OpenRouter · SentenceTransformers  
**Database** — Neon PostgreSQL · pgvector (768-dim cosine similarity) · SQLAlchemy 2 async

---

## Quick Start

### Prerequisites

- Python 3.11 (`brew install python@3.11`)
- Node.js 18+ (`brew install node`)
- Neon PostgreSQL account (free tier works)
- OpenRouter API key (free tier works)

### 1. Clone & configure

```bash
git clone https://github.com/Nakshatra480/RazorShield-AI.git
cd RazorShield-AI

# Copy and fill in your credentials
cp .env.example .env
# Edit .env with your OPENROUTER_API_KEY and DATABASE_URL
```

### 2. Install backend dependencies

```bash
bash razorshield_backend/setup.sh
```

This installs PyTorch (CPU), SentenceTransformers, Playwright Chromium, and all Python dependencies.

### 3. One-command launch

```bash
bash start.sh
```

This starts both servers concurrently and waits for the backend health check before opening the frontend:

- **Frontend:** http://localhost:3001  
- **Backend:** http://localhost:8000  
- **API Docs:** http://localhost:8000/api/docs

### 4. Manual launch (alternative)

```bash
# Terminal 1 — Backend
python3.11 -m uvicorn razorshield_backend.main:app --port 8000

# Terminal 2 — Frontend
npm run dev -- --port 3001
```

---

## Running the Benchmark

The benchmark evaluates the full pipeline against 50 programmatically-generated synthetic merchant profiles (35 safe + 15 high-risk). No live scraping — runs entirely offline.

```bash
python3.11 -m razorshield_backend.benchmark
```

Results are written to `public/benchmark_results.json` and automatically displayed in the **Benchmark & Metrics** tab of the UI.

You can also trigger the benchmark from the UI by clicking **"Run Benchmark Suite"** in the Benchmark tab.

---

## Testing the Inspect Endpoint

```bash
# Test with a real merchant URL
curl -X POST http://localhost:8000/api/v1/inspect \
  -H "Content-Type: application/json" \
  -d '{"url": "https://stripe.com"}'

# Check health
curl http://localhost:8000/api/v1/health

# List past scans
curl "http://localhost:8000/api/v1/scans?limit=10"
```

---

## Benchmark Results

Evaluated on 50 synthetic merchant profiles (Sep 2026):

| Metric | Score |
|---|---|
| Precision | **100.0%** |
| Recall | **100.0%** |
| F1-Score | **100.0%** |
| Avg Processing Time | ~3,200 ms/merchant |
| LLM calls saved (guardrails) | ~40% |

**Confusion Matrix:**

```
                  Predicted SAFE   Predicted HIGH_RISK
Actual SAFE           35                  0
Actual HIGH_RISK       0                 15
```

---

## Project Structure

```
RazorShield-AI/
├── app/                          # Next.js 14 App Router
│   ├── page.tsx                  # Main dashboard (Scanner / Feed / Benchmark tabs)
│   ├── layout.tsx                # Root layout + fonts
│   ├── globals.css               # Tailwind + design tokens
│   └── api/benchmark-results/   # Next.js API route serving benchmark JSON
├── components/
│   ├── scanner/                  # ScannerHeader, AgentPipeline, RiskScorecard
│   ├── benchmark/                # MetricCards, ConfusionMatrix, FinancialImpactChart
│   ├── feed/                     # RiskFeed (live DB data)
│   ├── layout/                   # Navbar
│   └── three/                    # ScannerGlobe (Three.js)
├── hooks/
│   ├── useMerchantScan.ts        # Real API calls to POST /api/v1/inspect
│   └── useBenchmarkData.ts       # Benchmark data + triggerBenchmark()
├── lib/
│   ├── api.ts                    # TypeScript API client
│   └── mockData.ts               # Type definitions + demo fallback data
├── razorshield_backend/
│   ├── main.py                   # FastAPI app + all endpoints
│   ├── config.py                 # Settings (env vars)
│   ├── benchmark.py              # 50-merchant synthetic evaluation
│   ├── agents/
│   │   ├── orchestrator.py       # asyncio.gather() multi-agent runner
│   │   ├── policy_agent.py       # LLM compliance checker
│   │   ├── catalog_agent.py      # pgvector similarity search
│   │   └── footprint_agent.py    # WHOIS + SSL inspector
│   ├── scrapers/
│   │   └── browser.py            # Playwright singleton manager
│   └── db/
│       ├── database.py           # SQLAlchemy async engine + pgvector init
│       └── models.py             # Merchant, Scan, ProhibitedPattern ORM models
├── start.sh                      # One-command concurrent launcher
├── .env.example                  # Environment variable template
├── SUBMISSION_FORM_RESPONSES.md  # Hackathon submission copy
└── README.md                     # This file
```

---

## Environment Variables

```bash
# .env
OPENROUTER_API_KEY=sk-or-...
DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname?sslmode=require
LLM_MODEL=openrouter/meta-llama/llama-3.1-70b-instruct
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5

# .env.local (frontend)
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Liveness probe |
| `POST` | `/api/v1/inspect` | Run full merchant inspection |
| `GET` | `/api/v1/scans` | List past scans (paginated) |
| `GET` | `/api/v1/scans/{id}` | Get single scan by UUID |
| `POST` | `/api/v1/benchmark/run` | Trigger benchmark evaluation |

Full interactive docs at **http://localhost:8000/api/docs**

---

## License

MIT © 2026 Nakshatra Sharma
