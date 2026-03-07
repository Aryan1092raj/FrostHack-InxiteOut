import asyncio
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from agents.state import CampaignState
from agents.profiler import profiler_node
from agents.strategist import strategist_node
from agents.content_gen import content_gen_node
from agents.executor import executor_node
from agents.monitor import monitor_node
from agents.optimizer import optimizer_node
from agents.base import emit
from shared import sse_queues, approval_events, approval_decisions
from db.database import (
    update_campaign_status,
    update_campaign_strategy,
    update_campaign_emails,
    get_campaign
)


# ─── Human Approval Node ──────────────────────────────────────────────────────

async def human_approval_node(state: CampaignState) -> dict:
    campaign_id = state["campaign_id"]

    # Save strategy and emails to DB so UI can display them
    if state.get("strategy"):
        update_campaign_strategy(campaign_id, state["strategy"])
    if state.get("emails"):
        update_campaign_emails(campaign_id, state["emails"])

    update_campaign_status(campaign_id, "awaiting_approval")

    await emit(campaign_id, "orchestrator", "approval_needed",
               "Campaign is ready for your review. Please approve or reject.",
               data={"campaign": get_campaign(campaign_id)})

    # Create event if it doesn't exist
    if campaign_id not in approval_events:
        approval_events[campaign_id] = asyncio.Event()
    else:
        approval_events[campaign_id].clear()

    # Wait for human decision
    await approval_events[campaign_id].wait()

    decision_data = approval_decisions.get(campaign_id, {"decision": "approved"})
    decision = decision_data.get("decision", "approved")
    reason = decision_data.get("reason", "")

    if decision == "rejected":
        await emit(campaign_id, "orchestrator", "agent_thought",
                   f"❌ Campaign rejected. Reason: {reason}. Re-planning...")
        return {
            "status": "planning",
            "rejection_reason": reason
        }
    else:
        await emit(campaign_id, "orchestrator", "agent_thought",
                   "✅ Campaign approved by human reviewer. Executing...")
        return {
            "status": "running",
            "rejection_reason": None
        }


# ─── Routing Functions ────────────────────────────────────────────────────────

async def entry_router(state: CampaignState) -> dict:
    """No-op node used as entry point for conditional routing."""
    return {}


def route_from_entry(state: CampaignState) -> str:
    """If resuming after server restart (emails exist, status=running), skip to executor."""
    if state.get("emails") and state["status"] == "running":
        return "executor"
    return "profiler"


def route_after_approval(state: CampaignState) -> str:
    if state["status"] == "running":
        return "executor"
    else:
        return "strategist"  # rejected — re-plan


def route_after_optimizer(state: CampaignState) -> str:
    if state["status"] == "done":
        return "end"
    else:
        return "strategist"  # continue optimizing


# ─── Build Graph ──────────────────────────────────────────────────────────────

def build_graph():
    workflow = StateGraph(CampaignState)

    # Add all nodes
    workflow.add_node("entry_router", entry_router)
    workflow.add_node("profiler", profiler_node)
    workflow.add_node("strategist", strategist_node)
    workflow.add_node("content_gen", content_gen_node)
    workflow.add_node("human_approval", human_approval_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("monitor", monitor_node)
    workflow.add_node("optimizer", optimizer_node)

    # Entry point — routes to profiler (fresh) or executor (resume)
    workflow.set_entry_point("entry_router")
    workflow.add_conditional_edges(
        "entry_router",
        route_from_entry,
        {"profiler": "profiler", "executor": "executor"}
    )

    # Fixed edges
    workflow.add_edge("profiler", "strategist")
    workflow.add_edge("strategist", "content_gen")
    workflow.add_edge("content_gen", "human_approval")
    workflow.add_edge("executor", "monitor")

    # Conditional edges
    workflow.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {
            "executor": "executor",
            "strategist": "strategist"
        }
    )

    workflow.add_conditional_edges(
        "optimizer",
        route_after_optimizer,
        {
            "strategist": "strategist",
            "end": END
        }
    )

    workflow.add_edge("monitor", "optimizer")

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


# ─── Run Pipeline ─────────────────────────────────────────────────────────────

async def run_campaign_pipeline(campaign_id: str, brief: str, resume_state: dict = None):
    """
    Main entry point called by main.py.
    Runs the full LangGraph agent pipeline for a campaign.
    If resume_state is provided, resumes from executor (e.g. after server restart).
    """
    queue = sse_queues.get(campaign_id)

    try:
        graph = build_graph()

        if resume_state:
            initial_state = resume_state
        else:
            initial_state: CampaignState = {
                "campaign_id": campaign_id,
                "brief": brief,
                "customers": [],
                "segments": [],
                "strategy": {},
                "emails": [],
                "external_campaign_ids": [],
                "metrics": {},
                "iteration": 1,
                "max_iterations": 3,
                "rejection_reason": None,
                "optimization_notes": "",
                "status": "planning"
            }

        config = {"configurable": {"thread_id": campaign_id}}

        await emit(campaign_id, "orchestrator", "agent_thought",
                   "🚀 CampaignX agent pipeline started. Initializing all agents...")

        # Stream the graph execution
        async for event in graph.astream(initial_state, config=config):
            node_name = list(event.keys())[0] if event else "unknown"
            if node_name != "__end__":
                pass  # SSE events are emitted inside each node

        update_campaign_status(campaign_id, "done")

        await emit(campaign_id, "orchestrator", "done",
                   "🏁 Campaign pipeline complete! Check the Reports page for final metrics.",
                   data={"campaign_id": campaign_id})

    except Exception as e:
        print(f"[Orchestrator] Exception: {str(e)}")
        # If we have metrics, campaign actually succeeded
        campaign = get_campaign(campaign_id)
        if campaign and campaign.get("metrics"):
            update_campaign_status(campaign_id, "done")
            await emit(campaign_id, "orchestrator", "done",
                       f"Campaign complete with metrics. Minor error: {str(e)[:80]}")
        else:
            update_campaign_status(campaign_id, "error")
            await emit(campaign_id, "orchestrator", "error",
                       f"Pipeline error: {str(e)}")

        if queue:
            await queue.put({
                "type": "error",
                "agent": "orchestrator",
                "message": f"Fatal error: {str(e)}",
                "data": {}
            })
