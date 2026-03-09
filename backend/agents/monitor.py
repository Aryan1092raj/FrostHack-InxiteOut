import asyncio
from typing import Any
from agents.state import CampaignState
from agents.base import emit, get_llm, invoke_with_retry
from tools.campaignx_tools import tool_get_report
from db.database import save_report, update_campaign_metrics


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

    all_metrics: dict[str, Any] = {
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

        # Accumulate
        all_metrics["total_sent"] += total
        all_metrics["opens"] += opens
        all_metrics["clicks"] += clicks

        email_info = email_by_ext_id.get(ext_id, {})
        all_metrics["per_campaign"].append({
            "external_campaign_id": ext_id,
            "open_rate": open_rate,
            "click_rate": click_rate,
            "total_sent": total,
            "subject": email_info.get("subject", ""),
            "tone": email_info.get("tone", ""),
            "customer_ids": email_info.get("customer_ids", []),
        })

        # Save to DB
        save_report(campaign_id, ext_id, open_rate, click_rate, total, result)

        await emit(campaign_id, "monitor", "agent_thought",
                   f"📊 Campaign {ext_id[:8]}...: "
                   f"Open {open_rate:.1%} | Click {click_rate:.1%} | "
                   f"Sent {total}")

    # Compute overall rates
    total_sent = all_metrics["total_sent"]
    if total_sent > 0:
        all_metrics["open_rate"] = round(all_metrics["opens"] / total_sent, 4)
        all_metrics["click_rate"] = round(all_metrics["clicks"] / total_sent, 4)

    # LLM analysis
    llm = get_llm(temperature=0.3)
    analysis_prompt = f"""Analyze these email campaign results for XDeposit:

Overall Metrics:
- Open Rate: {all_metrics['open_rate']:.1%}
- Click Rate: {all_metrics['click_rate']:.1%}
- Total Sent: {all_metrics['total_sent']}

Per-Campaign Breakdown:
{all_metrics['per_campaign']}

Campaign Brief: {state['brief']}
Current Iteration: {state.get('iteration', 1)}

Provide a 2-3 sentence analysis of performance and what needs improvement.
Focus on click rate (it's weighted 70% in scoring).
Be specific about which segments or variants underperformed."""

    try:
        analysis_raw = await invoke_with_retry(llm, analysis_prompt)
        analysis = analysis_raw.strip()
    except:
        analysis = (
            f"Open rate {all_metrics['open_rate']:.1%}, "
            f"click rate {all_metrics['click_rate']:.1%}. "
            f"Optimization needed to improve click-through engagement."
        )

    all_metrics["analysis"] = analysis

    # Update DB
    update_campaign_metrics(campaign_id, {
        "open_rate": all_metrics["open_rate"],
        "click_rate": all_metrics["click_rate"],
        "total_sent": all_metrics["total_sent"],
        "opens": all_metrics["opens"],
        "clicks": all_metrics["clicks"],
        "analysis": analysis
    })

    await emit(campaign_id, "monitor", "agent_thought",
               f"📈 Overall: Open {all_metrics['open_rate']:.1%} | "
               f"Click {all_metrics['click_rate']:.1%} | "
               f"Sent {all_metrics['total_sent']}")
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
