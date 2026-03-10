import asyncio
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from agents.state import CampaignState
from agents.profiler import profiler_node
from agents.strategist import strategist_node
from agents.content_gen import content_gen_node
from agents.probe_executor import probe_executor_node
from agents.executor import executor_node
from agents.monitor import monitor_node
from agents.optimizer import optimizer_node
from agents.base import emit
from shared import sse_queues, approval_events, approval_decisions
from db.database import (
    update_campaign_status,
    update_campaign_strategy,
    update_campaign_emails,
    get_campaign,
)


# ─── Human Approval Node ──────────────────────────────────────────────────────

async def human_approval_node(state: CampaignState) -> dict:
    campaign_id = state["campaign_id"]

    if state.get("strategy"):
        update_campaign_strategy(campaign_id, state["strategy"])
    if state.get("emails"):
        update_campaign_emails(campaign_id, state["emails"])

    update_campaign_status(campaign_id, "awaiting_approval")

    await emit(campaign_id, "orchestrator", "approval_needed",
               "Campaign is ready for your review. Please approve or reject.",
               data={"campaign": get_campaign(campaign_id)})

    if campaign_id not in approval_events:
        approval_events[campaign_id] = asyncio.Event()
    else:
        approval_events[campaign_id].clear()

    await approval_events[campaign_id].wait()

    decision_data = approval_decisions.get(campaign_id, {"decision": "approved"})
    decision      = decision_data.get("decision", "approved")
    reason        = decision_data.get("reason", "")

    if decision == "rejected":
        await emit(campaign_id, "orchestrator", "agent_thought",
                   f"❌ Campaign rejected. Reason: {reason}. Re-planning...")
        return {"status": "planning", "rejection_reason": reason}
    else:
        await emit(campaign_id, "orchestrator", "agent_thought",
                   "✅ Campaign approved by human reviewer. Starting probe phase...")
        return {"status": "running", "rejection_reason": None}


# ─── Routing Functions ────────────────────────────────────────────────────────

async def entry_router(state: CampaignState) -> dict:
    return {}


def route_from_entry(state: CampaignState) -> str:
    if state.get("emails") and state["status"] in {"running", "probe_done", "probe_failed", "probe_skipped"}:
        return "executor"
    return "profiler"


def route_after_approval(state: CampaignState) -> str:
    if state["status"] == "running":
        return "probe_executor"
    return "strategist"


def route_after_probe(state: CampaignState) -> str:
    """Always proceed to main executor after probe (whether probe succeeded or not)."""
    return "executor"


def route_after_optimizer(state: CampaignState) -> str:
    if state["status"] == "done":
        return "end"
    # FIX: If executor returned "error" status, stop the loop instead of retrying infinitely
    if state["status"] == "error":
        return "end"
    return "strategist"


# ─── Build Graph ──────────────────────────────────────────────────────────────

def build_graph():
    workflow = StateGraph(CampaignState)

    workflow.add_node("entry_router",   entry_router)
    workflow.add_node("profiler",       profiler_node)
    workflow.add_node("strategist",     strategist_node)
    workflow.add_node("content_gen",    content_gen_node)
    workflow.add_node("human_approval", human_approval_node)
    workflow.add_node("probe_executor", probe_executor_node)
    workflow.add_node("executor",       executor_node)
    workflow.add_node("monitor",        monitor_node)
    workflow.add_node("optimizer",      optimizer_node)

    workflow.set_entry_point("entry_router")
    workflow.add_conditional_edges(
        "entry_router",
        route_from_entry,
        {"profiler": "profiler", "executor": "executor"}
    )

    workflow.add_edge("profiler",    "strategist")
    workflow.add_edge("strategist",  "content_gen")
    workflow.add_edge("content_gen", "human_approval")
    workflow.add_edge("executor",    "monitor")
    workflow.add_edge("monitor",     "optimizer")

    workflow.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {"probe_executor": "probe_executor", "strategist": "strategist"}
    )

    workflow.add_conditional_edges(
        "probe_executor",
        route_after_probe,
        {"executor": "executor"}
    )

    workflow.add_conditional_edges(
        "optimizer",
        route_after_optimizer,
        {"strategist": "strategist", "end": END}
    )

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


# ─── Run Pipeline ─────────────────────────────────────────────────────────────

async def run_campaign_pipeline(campaign_id: str, brief: str, resume_state: dict = None):
    queue = sse_queues.get(campaign_id)

    try:
        graph = build_graph()

        if resume_state:
            initial_state = resume_state
        else:
            initial_state: CampaignState = {
                "campaign_id":                campaign_id,
                "brief":                      brief,
                "customers":                  [],
                "segments":                   [],
                "strategy":                   {},
                "emails":                     [],
                "external_campaign_ids":      [],
                "metrics":                    {},
                "iteration":                  1,
                "max_iterations":             5,
                "rejection_reason":           None,
                "optimization_notes":         "",
                "status":                     "planning",
                "underperforming_customer_ids": [],
                "winning_variant_info":       {},
                "all_emailed_customer_ids":   [],
                "all_converted_customer_ids": [],
                # Innovation fields
                "probe_results":              [],
                "thompson_winner":            {},
                "main_pool_customer_ids":     [],
                "email_dna_signal":           {},
                "winning_dna":               {},
                "dna_content_rules":          "",
                "api_signal_history":         [],
            }

        config = {"configurable": {"thread_id": campaign_id}}

        await emit(campaign_id, "orchestrator", "agent_thought",
                   "🚀 CampaignX agent pipeline started — SmartSplit + Thompson Sampling active.")

        async for event in graph.astream(initial_state, config=config):
            node_name = list(event.keys())[0] if event else "unknown"
            if node_name != "__end__":
                pass

        update_campaign_status(campaign_id, "done")
        await emit(campaign_id, "orchestrator", "done",
                   "🏁 Campaign pipeline complete! Check the Reports page for final metrics.",
                   data={"campaign_id": campaign_id})

    except Exception as e:
        # FIX: Print full traceback to Render logs so we can see exactly where it failed
        import traceback
        full_trace = traceback.format_exc()
        print(f"[Orchestrator] Exception for campaign {campaign_id}:\n{full_trace}")

        from db.database import get_campaign
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
                "type":    "error",
                "agent":   "orchestrator",
                "message": f"Fatal error: {str(e)}",
                "data":    {}
            })