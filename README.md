# CampaignX — AI Multi-Agent Email Campaign Platform

**Live Demo:** https://frost-hack-inxite-out.vercel.app/

---

## What It Does

CampaignX autonomously runs email campaigns for SuperBFSI's XDeposit term deposit product. An 8-node LangGraph pipeline handles customer segmentation, A/B strategy planning, content generation, probe-based winner selection, campaign execution, performance monitoring, and optimization — with human approval before every send.

## Architecture

```
Profiler → Strategist → Content Gen → Human Approval → Probe Executor → Executor → Monitor → Optimizer
               ↑           [reject] ←──┘                                                         ↓
               └──────────────────────────── [re-optimize] ←──────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | LangGraph (StateGraph + conditional edges) |
| LLMs | Groq (Llama 3.3 70B) primary, Gemini 1.5 Flash fallback |
| Backend | FastAPI, SSE streaming, SQLite |
| Frontend | React 19, TypeScript, Vite, Recharts |
| Deployment | Render (backend), Vercel (frontend) |
| API Integration | Dynamic tool calling from embedded OpenAPI 3.0 spec |

## Agent Pipeline

1. **Profiler** — Fetches the full customer cohort from the CampaignX API, LLM creates 3–5 demographic segments
2. **Strategist** — Designs 2 A/B variants with different tones, send times, and segment targeting
3. **Content Gen** — LLM writes email subject + body per variant (enforces API format rules)
4. **Human Approval** — Pipeline blocks until marketer approves or rejects (rejection feeds back to strategist)
5. **Probe Executor** — Tests micro-variants on a small probe pool and picks a winner with Thompson sampling
6. **Executor** — Sends campaigns via CampaignX send_campaign API
7. **Monitor** — Fetches reports, computes open/click rates, LLM analyzes performance
8. **Optimizer** — Evaluates results and loops back for rescue iterations up to the configured cap

## Key Features

- **Dynamic API Discovery** — Tools read OpenAPI spec at runtime to discover endpoints and validate payloads
- **Dual LLM Failover** — Auto-switches from Groq to Gemini on rate limits mid-retry
- **Real-Time SSE Stream** — Live terminal showing every agent's thought process as it runs
- **A/B Testing** — Every campaign creates 2 variants, optimizer evaluates per-variant performance
- **Human-in-the-Loop** — Approval required before every campaign send (including optimization re-launches)

## Setup

### Backend
```bash
cd backend
pip install -r requirements.txt
# Set env vars: GROQ_API_KEY, GEMINI_API_KEY, CAMPAIGNX_API_KEY, CAMPAIGNX_BASE_URL
uvicorn main:app --reload
```

### Frontend
```bash
cd frontend
npm install
# Set VITE_API_URL in .env
npm run dev
```

## Team

**FrostHack — InxiteOut**
