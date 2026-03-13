"""
monitor.py — Fetch reports and compute metrics.

Issues fixed in this rewrite:
  1. Per-iteration metrics stored separately from cumulative. The optimizer
     receives per-iteration click_rate so its stop decisions are based on
     "how did THIS send perform" not "average across all time including probes".
  2. Winning variant identification uses external_campaign_id matching via
     email["external_campaign_id"] set by executor, not fragile index pairing.
  3. Report saved with iteration_number so the chart groups correctly.
"""

import asyncio
from typing import Any
from agents.state import CampaignState
from agents.base import emit, get_llm, invoke_with_retry
from tools.campaignx_tools import tool_get_report
from db.database import save_report, update_campaign_metrics, get_all_reports_for_campaign


async def monitor_node(state: CampaignState) -> dict:
    campaign_id          = state["campaign_id"]
    external_campaign_ids = state.get("external_campaign_ids", [])
    iteration            = state.get("iteration", 1)

    await emit(campaign_id, "monitor", "agent_thought",
               f"Fetching reports for {len(external_campaign_ids)} campaigns "
               f"(iteration {iteration})...")

    # Build lookup: external_id → email metadata set by executor
    email_by_ext_id: dict = {}
    for email in state.get("emails", []):
        ext_id = email.get("external_campaign_id", "")
        if ext_id:
            email_by_ext_id[ext_id] = email

    # Small wait for gamified metrics to register
    await asyncio.sleep(2)

    # ── Fetch and aggregate per-iteration metrics ─────────────────────────────
    current: dict[str, Any] = {
        "open_rate":    0.0,
        "click_rate":   0.0,
        "total_sent":   0,
        "opens":        0,
        "clicks":       0,
        "per_campaign": [],
    }

    for ext_id in external_campaign_ids:
        await emit(campaign_id, "monitor", "action",
                   f"Fetching report for {ext_id[:12]}...")

        result = tool_get_report(ext_id)

        if "error" in result:
            await emit(campaign_id, "monitor", "agent_thought",
                       f"⚠️ Report error for {ext_id[:12]}: {result['error']}")
            continue

        computed   = result.get("computed_metrics", {})
        open_rate  = computed.get("open_rate", 0.0)
        click_rate = computed.get("click_rate", 0.0)
        total      = computed.get("total_sent", 0)
        opens      = computed.get("opens", 0)
        clicks     = computed.get("clicks", 0)

        current["total_sent"] += total
        current["opens"]      += opens
        current["clicks"]     += clicks

        email_meta = email_by_ext_id.get(ext_id, {})
        current["per_campaign"].append({
            "external_campaign_id": ext_id,
            "open_rate":            open_rate,
            "click_rate":           click_rate,
            "total_sent":           total,
            "opens":                opens,
            "clicks":               clicks,
            "subject":              email_meta.get("subject", ""),
            "tone":                 email_meta.get("tone", ""),
            "variant":              email_meta.get("variant", ""),
            "customer_ids":         email_meta.get("customer_ids", []),
        })

        # Save to DB with iteration_number for chart grouping
        save_report(
            campaign_id=campaign_id,
            external_id=ext_id,
            open_rate=open_rate,
            click_rate=click_rate,
            total_sent=total,
            raw_report=result,
            iteration_number=iteration,
        )

        await emit(campaign_id, "monitor", "agent_thought",
                   f"📊 {ext_id[:12]}...: Open {open_rate:.1%} | "
                   f"Click {click_rate:.1%} | Sent {total}")

    # Compute rates for THIS iteration
    if current["total_sent"] > 0:
        current["open_rate"]  = round(current["opens"]  / current["total_sent"], 4)
        current["click_rate"] = round(current["clicks"] / current["total_sent"], 4)

    # ── Cumulative metrics (for header stats display) ─────────────────────────
    try:
        historical      = get_all_reports_for_campaign(campaign_id)
        cum_sent        = sum(r.get("total_sent", 0) for r in historical)
        cum_opens       = sum(r.get("opens",      0) for r in historical)
        cum_clicks      = sum(r.get("clicks",     0) for r in historical)
        cum_open_rate   = round(cum_opens  / cum_sent, 4) if cum_sent > 0 else 0
        cum_click_rate  = round(cum_clicks / cum_sent, 4) if cum_sent > 0 else 0
    except Exception:
        cum_sent       = current["total_sent"]
        cum_opens      = current["opens"]
        cum_clicks     = current["clicks"]
        cum_open_rate  = current["open_rate"]
        cum_click_rate = current["click_rate"]

    # ── LLM analysis ──────────────────────────────────────────────────────────
    llm = get_llm(temperature=0.3)
    per_campaign_clean = [
        {k: v for k, v in pc.items() if k != "customer_ids"}
        for pc in current["per_campaign"]
    ]

    analysis_prompt = f"""Analyse these email campaign results for XDeposit:

Iteration {iteration} metrics:
- Open Rate:  {current['open_rate']:.1%}  ({current['opens']} customers opened)
- Click Rate: {current['click_rate']:.1%} ({current['clicks']} customers clicked)
- Total Sent: {current['total_sent']}

Cumulative across all iterations:
- Open Rate:  {cum_open_rate:.1%}
- Click Rate: {cum_click_rate:.1%}
- Total Sent: {cum_sent}

Per-campaign breakdown:
{per_campaign_clean}

Campaign Brief: {state['brief']}

Give a 2-3 sentence analysis. Focus on:
1. Which variant performed better and why
2. What specifically should change in the next iteration
3. Click rate matters 70% — what is dragging it down?"""

    try:
        analysis = await invoke_with_retry(llm, analysis_prompt)
    except Exception:
        analysis = (
            f"Iteration {iteration}: Open {current['open_rate']:.1%}, "
            f"Click {current['click_rate']:.1%}. "
            f"{'Click rate needs improvement.' if current['click_rate'] < 0.20 else 'Performance acceptable.'}"
        )

    await emit(campaign_id, "monitor", "agent_thought",
               f"📈 Iteration {iteration} — Open: {current['open_rate']:.1%} | "
               f"Click: {current['click_rate']:.1%}")
    await emit(campaign_id, "monitor", "agent_thought", f"🔍 Analysis: {analysis}")

    # Store cumulative in campaign record (for header display)
    # Store per-iteration in metrics dict (for optimizer decisions)
    cumulative_for_display = {
        "open_rate":    cum_open_rate,
        "click_rate":   cum_click_rate,
        "total_sent":   cum_sent,
        "opens":        cum_opens,
        "clicks":       cum_clicks,
        "per_campaign": current["per_campaign"],  # current iteration breakdown
        "analysis":     analysis,
    }
    update_campaign_metrics(campaign_id, cumulative_for_display)

    # Metrics passed to optimizer uses PER-ITERATION rates, not cumulative
    # This prevents the optimizer from making stop decisions based on diluted averages
    optimizer_metrics = {
        "open_rate":    current["open_rate"],
        "click_rate":   current["click_rate"],
        "total_sent":   current["total_sent"],
        "opens":        current["opens"],
        "clicks":       current["clicks"],
        "per_campaign": current["per_campaign"],
        "analysis":     analysis,
        # Also pass cumulative for context
        "cumulative_open_rate":  cum_open_rate,
        "cumulative_click_rate": cum_click_rate,
        "cumulative_sent":       cum_sent,
    }

    return {
        "metrics": optimizer_metrics,
        "status":  "monitored",
    }