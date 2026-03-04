import json
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json
from db.database import increment_campaign_iteration


async def optimizer_node(state: CampaignState) -> dict:
    campaign_id = state["campaign_id"]
    metrics = state.get("metrics", {})
    segments = state.get("segments", [])
    emails = state.get("emails", [])
    iteration = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 3)

    await emit(campaign_id, "optimizer", "agent_thought",
               f"Analyzing results for optimization (iteration {iteration}/{max_iterations})...")

    open_rate = metrics.get("open_rate", 0)
    click_rate = metrics.get("click_rate", 0)
    per_campaign = metrics.get("per_campaign", [])
    analysis = metrics.get("analysis", "")

    await emit(campaign_id, "optimizer", "agent_thought",
               f"Current scores: Open {open_rate:.1%} | Click {click_rate:.1%}")

    # Check if we should stop
    if iteration >= max_iterations:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"✅ Reached max iterations ({max_iterations}). Campaign complete.")
        return {"status": "done", "optimization_notes": "Max iterations reached"}

    if click_rate >= 0.50 and open_rate >= 0.40:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🏆 Excellent results achieved! Click {click_rate:.1%} ≥ 50%. Stopping.")
        return {"status": "done", "optimization_notes": "Target metrics achieved"}

    # LLM decides optimization strategy
    llm = get_llm(temperature=0.5)

    prompt = f"""You are a campaign optimization expert for SuperBFSI's XDeposit campaign.

Current Results (Iteration {iteration}):
- Open Rate: {open_rate:.1%} (target: >40%)
- Click Rate: {click_rate:.1%} (target: >50%, weighted 70% in scoring)
- Total Sent: {metrics.get('total_sent', 0)}

Performance Analysis: {analysis}

Per-Campaign Breakdown:
{json.dumps(per_campaign, indent=2)}

Current Segments:
{json.dumps([{{'id': s['segment_id'], 'name': s['name'], 'size': s['size']}} for s in segments], indent=2)}

Current Email Variants:
{json.dumps([{{'variant': e['variant'], 'subject': e['subject'][:80], 'customers': len(e['customer_ids'])}} for e in emails], indent=2)}

Based on this data, provide specific optimization recommendations.
Focus on improving CLICK RATE (highest priority).

Return ONLY this JSON:
{{
    "should_continue": true,
    "optimization_notes": "Specific instructions for next iteration: what to change in content, tone, timing, segments",
    "focus_areas": ["click_rate improvement", "subject line testing"],
    "micro_segments_to_retarget": ["segment names that underperformed"],
    "content_adjustments": "What to change in email content",
    "timing_adjustments": "What to change in send times"
}}"""

    try:
        response = llm.invoke(prompt)
        result = json.loads(clean_llm_json(response.content))

        should_continue = result.get("should_continue", True)
        notes = result.get("optimization_notes", "")
        focus = result.get("focus_areas", [])
        content_adj = result.get("content_adjustments", "")
        timing_adj = result.get("timing_adjustments", "")

        full_notes = (
            f"Iteration {iteration} insights: {notes}. "
            f"Focus: {', '.join(focus)}. "
            f"Content: {content_adj}. "
            f"Timing: {timing_adj}."
        )

        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🔧 Optimization plan: {notes}")
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🎯 Focus areas: {', '.join(focus)}")

        if not should_continue:
            await emit(campaign_id, "optimizer", "agent_thought",
                       "✅ Optimizer determined campaign is performing well. Stopping.")
            return {"status": "done", "optimization_notes": full_notes}

        # Increment iteration
        increment_campaign_iteration(campaign_id)

        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🔄 Launching optimization iteration {iteration + 1}...")

        return {
            "iteration": iteration + 1,
            "optimization_notes": full_notes,
            "rejection_reason": None,
            "status": "optimizing"
        }

    except Exception as e:
        await emit(campaign_id, "optimizer", "error",
                   f"Optimizer error: {str(e)}. Stopping loop.")
        return {"status": "done", "optimization_notes": f"Optimizer error: {str(e)}"}
