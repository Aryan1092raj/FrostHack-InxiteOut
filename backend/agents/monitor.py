import asyncio
from typing import Any
from agents.state import CampaignState
from agents.base import emit, get_llm, invoke_with_retry
from tools.campaignx_tools import tool_get_report
from db.database import save_report, update_campaign_metrics, get_all_reports_for_campaign


async def monitor_node(state: CampaignState) -> dict:
    campaign_id = state["campaign_id"]
    external_campaign_ids = state.get("external_campaign_ids", [])

    await emit(campaign_id, "monitor", "agent_thought",
               f"Fetching performance reports for {len(external_campaign_ids)} campaigns...")

    # Build lookup: external_id → email details (emails[i] ↔ external_campaign_ids[i])
    email_by_ext_id: dict = {}
    for i, ext_id in enumerate(external_campaign_ids):
        if i < len(state.get("emails", [])):
            email_by_ext_id[ext_id] = state["emails"][i]

    # Small wait to allow gamified metrics to register
    await asyncio.sleep(2)

    # ── Current iteration metrics ─────────────────────────────────────────────────────
    current_metrics: dict[str, Any] = {
        "open_rate": 0.0,
        "click_rate": 0.0,
        "total_sent": 0,
        "opens": 0,
        "clicks": 0,
        "per_campaign": []
    }

    for ext_id in external_campaign_ids:
        await emit(campaign_id, "monitor", "action",
                   f"Fetching report for campaign {ext_id}...")

        result = tool_get_report(ext_id)

        if "error" in result:
            await emit(campaign_id, "monitor", "agent_thought",
                       f"⚠️ Report issue for {ext_id}: {result['error']}")
            continue

        computed = result.get("computed_metrics", {})
        open_rate = computed.get("open_rate", 0.0)
        click_rate = computed.get("click_rate", 0.0)
        total = computed.get("total_sent", 0)
        opens = computed.get("opens", 0)
        clicks = computed.get("clicks", 0)

        # Accumulate current iteration
        current_metrics["total_sent"] += total
        current_metrics["opens"] += opens
        current_metrics["clicks"] += clicks

        email_info = email_by_ext_id.get(ext_id, {})
        current_metrics["per_campaign"].append({
            "external_campaign_id": ext_id,
            "open_rate": open_rate,
            "click_rate": click_rate,
            "total_sent": total,
            "subject": email_info.get("subject", ""),
            "tone": email_info.get("tone", ""),
            "customer_ids": email_info.get("customer_ids", []),
        })

        # Save to DB (with opens/clicks and iteration number for chart grouping)
        save_report(campaign_id, ext_id, open_rate, click_rate, total, result,
                    iteration_number=state.get("iteration", 1))

        await emit(campaign_id, "monitor", "agent_thought",
                   f"📊 Campaign {ext_id[:8]}...: "
                   f"Open {open_rate:.1%} | Click {click_rate:.1%} | "
                   f"Sent {total}")

    # ── FIX: Compute CUMULATIVE metrics across ALL iterations ─────────────────
    # Load all historical reports for this campaign from DB
    try:
        all_historical = get_all_reports_for_campaign(campaign_id)
        cumulative_sent = sum(r.get("total_sent", 0) for r in all_historical)
        cumulative_opens = sum(r.get("opens", 0) for r in all_historical)
        cumulative_clicks = sum(r.get("clicks", 0) for r in all_historical)
    except Exception as e:
        print(f"[Monitor] Could not load historical reports: {e}. Using current iteration only.")
        cumulative_sent = current_metrics["total_sent"]
        cumulative_opens = current_metrics["opens"]
        cumulative_clicks = current_metrics["clicks"]

    all_metrics = dict(current_metrics)  # keep per_campaign from current iteration
    all_metrics["total_sent"] = cumulative_sent
    all_metrics["opens"] = cumulative_opens
    all_metrics["clicks"] = cumulative_clicks

    if cumulative_sent > 0:
        all_metrics["open_rate"] = round(cumulative_opens / cumulative_sent, 4)
        all_metrics["click_rate"] = round(cumulative_clicks / cumulative_sent, 4)
    elif current_metrics["total_sent"] > 0:
        all_metrics["open_rate"] = round(current_metrics["opens"] / current_metrics["total_sent"], 4)
        all_metrics["click_rate"] = round(current_metrics["clicks"] / current_metrics["total_sent"], 4)

    # ── LLM analysis ───────────────────────────────────────────────────────────────────
    llm = get_llm(temperature=0.3)
    iteration = state.get("iteration", 1)
    per_campaign_for_analysis = [
        {k: v for k, v in pc.items() if k != "customer_ids"}
        for pc in current_metrics["per_campaign"]
    ]
    analysis_prompt = f"""Analyze these email campaign results for XDeposit:

Overall Cumulative Metrics (across all {iteration} iteration(s)):
- Open Rate: {all_metrics['open_rate']:.1%}
- Click Rate: {all_metrics['click_rate']:.1%}
- Total Sent: {all_metrics['total_sent']}

Current Iteration Metrics:
- Sent this iteration: {current_metrics['total_sent']}

Per-Campaign Breakdown (this iteration):
{per_campaign_for_analysis}

Campaign Brief: {state['brief']}
Current Iteration: {iteration}

Provide a 2-3 sentence analysis of performance and what needs improvement.
Focus on click rate (it's weighted 70% in scoring).
Be specific about which segments or variants underperformed."""

    try:
        analysis_raw = await invoke_with_retry(llm, analysis_prompt)
        analysis = analysis_raw.strip()
    except Exception as e:
        print(f"[Monitor] LLM analysis failed: {e}")
        await emit(campaign_id, "monitor", "agent_thought",
                   f"⚠️ LLM analysis failed ({type(e).__name__}): {str(e)[:100]}. Using fallback.")
        analysis = (
            f"Cumulative open rate {all_metrics['open_rate']:.1%}, "
            f"click rate {all_metrics['click_rate']:.1%} across {all_metrics['total_sent']} emails. "
            f"Current iteration ({iteration}) targeted {current_metrics['total_sent']} customers. "
            f"Optimization needed to improve click-through engagement."
        )

    all_metrics["analysis"] = analysis

    # Update DB with cumulative metrics
    update_campaign_metrics(campaign_id, {
        "open_rate": all_metrics["open_rate"],
        "click_rate": all_metrics["click_rate"],
        "total_sent": all_metrics["total_sent"],
        "opens": all_metrics["opens"],
        "clicks": all_metrics["clicks"],
        "analysis": analysis
    })

    await emit(campaign_id, "monitor", "agent_thought",
               f"📈 Cumulative: Open {all_metrics['open_rate']:.1%} | "
               f"Click {all_metrics['click_rate']:.1%} | "
               f"Total Sent {all_metrics['total_sent']}")
    await emit(campaign_id, "monitor", "agent_thought",
               f"🔍 Analysis: {analysis}")
    await emit(campaign_id, "monitor", "metric_update",
               "Metrics updated",
               data={
                   "open_rate": all_metrics["open_rate"],
                   "click_rate": all_metrics["click_rate"],
                   "total_sent": all_metrics["total_sent"]
               })

    return {"metrics": all_metrics, "status": "monitored"}
