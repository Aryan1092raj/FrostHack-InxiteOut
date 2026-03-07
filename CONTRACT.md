# API Contract

## Full API Contract

### REST Endpoints (Backend exposes, Frontend calls)

| Method | Endpoint | What it does | Frontend uses it in |
|--------|----------|--------------|-------------------|
| POST | `/api/signup` | Register team, get API key (skips if in `.env`) | Settings page (once) |
| GET | `/api/cohort` | Get all customers (cached per day) | NewCampaign, Dashboard |
| POST | `/api/campaign/start` | Submit brief, start agent | NewCampaign page |
| POST | `/api/campaign/{id}/approve` | Human approves campaign | Approval screen |
| POST | `/api/campaign/{id}/reject` | Human rejects campaign | Approval screen |
| POST | `/api/campaign/{id}/stop` | Marketer stops optimization loop | Dashboard / Approval |
| GET | `/api/campaign/{id}/report` | Get performance metrics | Reports page |
| GET | `/api/campaign/{id}/status` | Poll current status (SSE fallback) | AgentThinkingStream |
| GET | `/api/campaigns` | List all past campaigns | Dashboard |
| GET | `/api/campaign/{id}` | Get single campaign details | Approval screen |
| GET | `/api/health` | Backend alive check | Health Check |

### SSE Endpoint (Real-time streaming)

| Endpoint | Stream events | Frontend uses it in |
|----------|--------------|-------------------|
| `GET /api/campaign/{id}/stream` | Agent thoughts, status updates | AgentThinkingStream component |

## Agreed JSON Shapes

**Campaign object:**
```json
{
  "id": "uuid",
  "status": "planning|awaiting_approval|running|monitoring|optimizing|done|stopped",
  "brief": "Run email campaign for XDeposit...",
  "iteration": 1,
  "max_iterations": 3,
  "campaign_ids_per_iteration": ["uuid1"],
  "agent_logs": [
    {
      "agent": "profiler",
      "thought": "Fetching active customers...",
      "timestamp": "2026-03-03T10:00:00Z"
    }
  ],
  "strategy": {
    "segments": [["CUST001", "CUST002"], ["CUST003", "CUST004"]],
    "send_times": ["03:03:26 09:00:00", "03:03:26 18:00:00"], 
    "ab_variants": ["variant_a", "variant_b"]
  },
  "emails": [
    {
      "variant": "variant_a",
      "subject": "Grow your savings with XDeposit 💰",
      "body": "Dear {name}, ...",
      "customer_ids": ["CUST001", "CUST002"]
    }
  ],
  "metrics": {
    "open_rate": 0.42,
    "click_rate": 0.18,
    "total_sent": 100
  },
  "created_at": "2026-03-03T10:00:00Z"
}
```

**SSE stream event:**
```json
// approval_needed
{ 
  "type": "approval_needed", 
  "agent": "orchestrator",
  "message": "Campaign planning complete. Awaiting human approval.",
  "data": { "campaign": { /* full campaign object */ } } 
}

// metric_update  
{ 
  "type": "metric_update", 
  "agent": "monitor",
  "message": "Fetched latest performance metrics.",
  "data": { "open_rate": 0.42, "click_rate": 0.18 } 
}

// action
{ 
  "type": "action", 
  "agent": "executor",
  "message": "Sending campaign variants.",
  "data": { "api_called": "send_campaign", "payload": { /* api payload */ } } 
}

// agent_thought
{
  "type": "agent_thought",
  "agent": "strategist",
  "message": "Segmenting customers by age and location...",
  "data": {}
}
```
