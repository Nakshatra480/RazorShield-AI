# RazorShield AI — Autonomous Merchant Risk Inspector

> Enterprise-grade autonomous multi-agent merchant onboarding risk inspector built for payment gateways and high-throughput acquirers.

![RazorShield AI Preview](https://raw.githubusercontent.com/Nakshatra480/RazorShield-AI/main/public/preview.png)

## Overview

**RazorShield AI** is an autonomous multi-agent risk assessment platform designed to replace manual underwriting workflows. Powered by a coordinated 4-agent inspection pipeline, RazorShield analyzes merchant domains, regulatory registries, transaction histories, and fraud indicators within seconds.

---

## Core Capabilities

### 1. Autonomous Multi-Agent Pipeline
- **Merchant Web Scraper Agent**: Headless browser extraction of catalog pricing, inventory depth, checkout flows, return policies, and Terms of Service clarity.
- **Regulatory & Registry Agent**: Cross-checks corporate registries, sanctions lists (OFAC, PEP, Interpol), and state-level business filings.
- **Transaction & Fraud History Agent**: Analyzes historical chargeback velocities, MATCH list records, and synthetic identity risk factors.
- **Underwriting & Risk Synthesis Agent**: Synthesizes multi-agent signals into a definitive verdict with actionable risk drivers and automated audit logs.

### 2. Risk Operations Live Feed
- Real-time tabular monitoring of queued, processing, and finalized merchant scans.
- Granular risk-tier tagging (`CRITICAL`, `ELEVATED`, `STANDARD`, `CLEAR`).
- Expandable merchant audit drawer with direct risk driver breakdown and inspector actions.

### 3. Precision Benchmark & Financial Impact Analytics
- Live performance scorecard tracking Precision (99.4%), Recall (98.7%), and Average Inspection Latency (3.2s).
- High-contrast **Confusion Matrix** detailing True Positives, False Positives, True Negatives, and False Negatives.
- **Financial Impact Area Chart** visualizing cumulative fraud loss prevention vs. false decline reduction.

---

## Tech Stack & Design System

- **Framework**: Next.js 14 (App Router) + TypeScript
- **Styling**: Tailwind CSS (Tailored Fintech Dark Palette — Deep Slate `#090D16`, Dark Card Surfaces `#111827`, Sub-Cards `#1F2937`)
- **Typography**: Inter (UI interfaces) + JetBrains Mono (Audit logs & domain telemetry)
- **3D Interactive Header**: Three.js & `@react-three/fiber` wireframe globe with dynamic scanning particles
- **Animations**: Framer Motion (page transitions, collapsible agent accordions, timeline indicators)
- **Visualizations**: Recharts (Financial impact area trends) & SVG dynamic arc gauge counters
- **Icons**: Lucide React

---

## Getting Started

### Prerequisites
- Node.js 18.17+ or 20+
- npm or yarn

### Installation

```bash
git clone https://github.com/Nakshatra480/RazorShield-AI.git
cd RazorShield-AI
npm install
```

### Development Server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to view the application.

### Production Build

```bash
npm run build
npm run start
```

---

## Architecture

```
app/
 ├── globals.css           # Custom scrollbars, scanner grid, scan-line animations
 ├── layout.tsx            # Inter & JetBrains Mono font configuration
 └── page.tsx              # Main view switching (Scanner, Feed, Benchmark)
components/
 ├── layout/
 │    └── Navbar.tsx       # Live status indicators & Framer tab indicator
 ├── three/
 │    └── ScannerGlobe.tsx # React Three Fiber 3D interactive wireframe globe
 ├── scanner/
 │    ├── ScannerHeader.tsx
 │    ├── AgentPipeline.tsx
 │    ├── RiskScorecard.tsx
 │    ├── AgentAccordion.tsx
 │    └── AuditTrail.tsx
 ├── feed/
 │    └── RiskFeed.tsx
 └── benchmark/
      ├── MetricCards.tsx
      ├── ConfusionMatrix.tsx
      └── FinancialImpactChart.tsx
hooks/
 └── useScanSimulation.ts  # Multi-agent phased progress orchestration
lib/
 ├── mockData.ts           # Enterprise mock datasets for scans, feeds, and analytics
 └── utils.ts              # Risk badge utilities, millisecond formatters
```

---

## License

MIT © [RazorShield AI](https://github.com/Nakshatra480/RazorShield-AI)
