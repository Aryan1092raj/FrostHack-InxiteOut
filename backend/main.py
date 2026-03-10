import asyncio
import json
import itertools
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from db.database import (
    init_db,
    get_connection,
    create_campaign,
    get_campaign,
    get_all_campaigns,
    update_campaign_status,
    get_report,
    get_agent_logs,
    get_rate_limit_status,
    get_cached_cohort,
    save_cohort_cache,
    check_and_increment_rate_limit,
    clear_cohort_cache,
)
from task_manager import start_task, get_task, list_tasks, get_active_tasks
from db.schemas import (
    StartCampaignRequest,
    RejectCampaignRequest,
    SignupRequest,
)

import requests
from dotenv import load_dotenv
import os

load_dotenv()

# ─── App Setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="CampaignX Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://frost-hack-inxite-out.vercel.app",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CAMPAIGNX_BASE_URL = os.getenv("CAMPAIGNX_BASE_URL", "https://campaignx.inxiteout.ai")
CAMPAIGNX_API_KEY = os.getenv("CAMPAIGNX_API_KEY", "")

# ─── Shared In-Memory Stores (imported from shared.py) ───────────────────────
from shared import sse_queues, approval_events, approval_decisions


# ─── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()
    print("✅ CampaignX Backend started")


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.get("/ping")
async def ping():
    """Lightweight keep-alive for cron jobs — no API calls wasted."""
    return {"status": "alive"}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "rate_limits": get_rate_limit_status()
    }


# ─── Clear cohort cache (call once after preliminary round reset) ─────────────

@app.post("/api/cohort/clear-cache")
async def clear_cache():
    """
    DELETE all cached cohort data so next campaign fetches the fresh 1000-customer cohort.
    Call this ONCE after the preliminary round reset (new cohort live from 9 March 11:59 PM).
    """
    clear_cohort_cache()
    return {"status": "ok", "message": "Cohort cache cleared. Next campaign will fetch fresh cohort from API."}


# ─── Task manager endpoints ───────────────────────────────────────────────────

@app.get("/api/tasks")
async def list_all_tasks(campaign_id: str = None):
    """List background tasks — optionally filter by campaign_id."""
    return {"tasks": list_tasks(campaign_id)}


@app.get("/api/tasks/active")
async def active_tasks():
    """List only currently running tasks — useful for frontend spinner."""
    return {"tasks": get_active_tasks()}


@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str):
    """Poll a specific background task by its task_id."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task {task_id} not found")
    return task


# ─── Signup ───────────────────────────────────────────────────────────────────

@app.post("/api/signup")
async def signup(body: SignupRequest):
    """
    Register team with CampaignX API.
    Only call this once — key is stored in .env
    """
    if CAMPAIGNX_API_KEY:
        return {
            "message": "Already registered. API key exists in .env",
            "api_key": "".join(itertools.islice(str(CAMPAIGNX_API_KEY), 8)) + "..."  # partial for safety
        }

    allowed = check_and_increment_rate_limit("signup", max_calls=1)
    if not allowed:
        raise HTTPException(400, "Signup already attempted today")

    response = requests.post(
        f"{CAMPAIGNX_BASE_URL}/api/v1/signup",
        json={
            "team_name": body.team_name,
            "team_email": body.team_email
        }
    )

    if response.status_code != 201:
        raise HTTPException(response.status_code, response.text)

    data = response.json()
    return {
        "message": "Signup successful! Save your API key in .env as CAMPAIGNX_API_KEY",
        "api_key": data.get("api_key"),
        "team_name": data.get("team_name"),
    }


# ─── Customer Cohort ──────────────────────────────────────────────────────────

@app.get("/api/cohort")
async def get_cohort():
    """
    Returns customer cohort.
    Uses cache if already fetched today — saves rate limit.
    """
    # Check cache first
    cached = get_cached_cohort()
    if cached:
        return {
            "data": cached,
            "total_count": len(cached),
            "source": "cache"
        }

    # Not cached — hit real API
    allowed = check_and_increment_rate_limit("get_customer_cohort")
    if not allowed:
        raise HTTPException(429, "Rate limit reached for cohort endpoint today")

    response = requests.get(
        f"{CAMPAIGNX_BASE_URL}/api/v1/get_customer_cohort",
        headers={"X-API-Key": CAMPAIGNX_API_KEY}
    )

    if response.status_code != 200:
        raise HTTPException(response.status_code, response.text)

    data = response.json()
    customers = data.get("data", [])

    # Save to cache
    save_cohort_cache(customers)

    return {
        "data": customers,
        "total_count": len(customers),
        "source": "api"
    }


# ─── Campaign CRUD ────────────────────────────────────────────────────────────

@app.get("/api/campaigns")
async def list_campaigns():
    """List all campaigns — used by Dashboard"""
    campaigns = get_all_campaigns()
    return {
        "campaigns": campaigns,
        "total": len(campaigns)
    }


@app.get("/api/campaign/{campaign_id}")
async def get_campaign_by_id(campaign_id: str):
    """Get single campaign — used by Approval screen"""
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, f"Campaign {campaign_id} not found")
    return campaign


@app.get("/api/campaign/{campaign_id}/status")
async def get_campaign_status(campaign_id: str):
    """Lightweight status poll — frontend fallback if SSE drops"""
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, f"Campaign {campaign_id} not found")
    return {
        "campaign_id": campaign_id,
        "status": campaign["status"],
        "iteration": campaign["iteration"],
        "updated_at": campaign["updated_at"]
    }


@app.get("/api/campaign/{campaign_id}/report")
async def get_campaign_report(campaign_id: str):
    """Get performance metrics — used by Reports page"""
    report = get_report(campaign_id)
    if not report:
        raise HTTPException(404, f"No report found for campaign {campaign_id}")
    return report


@app.get("/api/campaign/{campaign_id}/reports")
async def get_campaign_reports_history(campaign_id: str):
    """Returns all reports for a campaign — used by optimization timeline chart."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM reports WHERE campaign_id = ?
        ORDER BY fetched_at ASC
    """, (campaign_id,)).fetchall()
    conn.close()

    reports = []
    for row in rows:
        report = dict(row)
        report["raw_report"] = json.loads(report["raw_report"]) if report["raw_report"] else {}
        reports.append(report)

    return {
        "campaign_id": campaign_id,
        "reports": reports,
        "total": len(reports)
    }


@app.get("/api/campaign/{campaign_id}/logs")
async def get_campaign_logs(campaign_id: str):
    """Get agent thought logs — bonus points feature"""
    logs = get_agent_logs(campaign_id)
    return {
        "campaign_id": campaign_id,
        "logs": logs,
        "total": len(logs)
    }


# ─── Campaign Actions ─────────────────────────────────────────────────────────

@app.post("/api/campaign/start")
async def start_campaign(body: StartCampaignRequest, background_tasks: BackgroundTasks):
    """
    Start a new campaign.
    Creates DB record, starts agent pipeline in background.
    """
    campaign_id = str(uuid.uuid4())

    # Create in DB
    campaign = create_campaign(campaign_id, body.brief)

    # Create SSE queue for this campaign
    sse_queues[campaign_id] = asyncio.Queue()

    # Create approval event for this campaign
    approval_events[campaign_id] = asyncio.Event()

    # Start agent pipeline in background (non-blocking)
    background_tasks.add_task(run_agent_pipeline, campaign_id, body.brief)

    return {
        "campaign_id": campaign_id,
        "status": "planning",
        "message": "Campaign started. Connect to SSE stream for live updates.",
        "stream_url": f"/api/campaign/{campaign_id}/stream"
    }


@app.post("/api/campaign/{campaign_id}/approve")
async def approve_campaign(campaign_id: str):
    """
    Human approves the campaign.
    Unblocks the agent pipeline to proceed with sending.
    """
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, f"Campaign {campaign_id} not found")

    if campaign["status"] != "awaiting_approval":
        raise HTTPException(400, f"Campaign is not awaiting approval. Status: {campaign['status']}")

    # Store decision
    approval_decisions[campaign_id] = {"decision": "approved", "reason": None}

    # Unblock the agent
    if campaign_id in approval_events:
        approval_events[campaign_id].set()
    else:
        # Campaign was restarted — recreate event and set immediately
        approval_events[campaign_id] = asyncio.Event()
        approval_events[campaign_id].set()

    update_campaign_status(campaign_id, "running")

    return {
        "campaign_id": campaign_id,
        "status": "running",
        "message": "Campaign approved. Agent is now executing."
    }


@app.post("/api/campaign/{campaign_id}/reject")
async def reject_campaign(campaign_id: str, body: RejectCampaignRequest):
    """
    Human rejects the campaign.
    Agent will re-plan based on rejection reason.
    """
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, f"Campaign {campaign_id} not found")

    if campaign["status"] != "awaiting_approval":
        raise HTTPException(400, f"Campaign is not awaiting approval. Status: {campaign['status']}")

    # Store decision with reason
    approval_decisions[campaign_id] = {
        "decision": "rejected",
        "reason": body.reason
    }

    # Unblock agent — it will check the decision and re-plan
    if campaign_id in approval_events:
        approval_events[campaign_id].set()

    update_campaign_status(campaign_id, "planning")

    return {
        "campaign_id": campaign_id,
        "status": "planning",
        "message": f"Campaign rejected. Agent will re-plan. Reason: {body.reason}"
    }


@app.post("/api/campaign/{campaign_id}/stop")
async def stop_campaign(campaign_id: str):
    """Marketer manually stops the optimization loop"""
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, f"Campaign {campaign_id} not found")

    update_campaign_status(campaign_id, "stopped")

    # Send stop signal via SSE
    if campaign_id in sse_queues:
        await sse_queues[campaign_id].put({
            "type": "done",
            "agent": "orchestrator",
            "message": "Campaign stopped by marketer.",
            "data": {}
        })

    return {
        "campaign_id": campaign_id,
        "status": "stopped"
    }


# ─── SSE Stream ───────────────────────────────────────────────────────────────

@app.get("/api/campaign/{campaign_id}/stream")
async def campaign_stream(campaign_id: str):
    """
    SSE endpoint — streams agent thoughts in real time to frontend.
    Frontend connects with EventSource('/api/campaign/{id}/stream')
    """
    # Create queue if it doesn't exist (e.g. page refresh)
    if campaign_id not in sse_queues:
        sse_queues[campaign_id] = asyncio.Queue()

    async def event_generator():
        queue = sse_queues[campaign_id]

        # Send initial connection confirmation
        yield {
            "data": json.dumps({
                "type": "connected",
                "agent": "orchestrator",
                "message": f"Connected to campaign {campaign_id} stream",
                "data": {}
            })
        }

        while True:
            try:
                # Wait for next event from agent (timeout to keep connection alive)
                event = await asyncio.wait_for(queue.get(), timeout=30.0)

                yield {"data": json.dumps(event)}

                # If done or error — close stream
                if event.get("type") in ["done", "error"]:
                    break

            except asyncio.TimeoutError:
                # Send keepalive ping so connection doesn't drop
                yield {
                    "data": json.dumps({
                        "type": "ping",
                        "agent": "orchestrator",
                        "message": "keepalive",
                        "data": {}
                    })
                }

    return EventSourceResponse(event_generator())


# ─── Agent Pipeline ───────────────────────────────────────────────────────────

async def run_agent_pipeline(campaign_id: str, brief: str):
    """Runs the real LangGraph agent pipeline."""
    from agents.orchestrator import run_campaign_pipeline
    await run_campaign_pipeline(campaign_id, brief)
