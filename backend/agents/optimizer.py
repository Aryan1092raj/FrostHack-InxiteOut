import json
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json, invoke_with_retry
from db.database import increment_campaign_iteration, get_reports_by_external_ids


async def optimizer_node(state: CampaignState) -> dict:
    campaign_id = state["campaign_id"]
    metrics = state.get("metrics", {})
    emails = state.get("emails", [])
    external_ids = state.get("external_campaign_ids", [])
    iteration = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 5)
    total_cohort = 1000  # final round fixed cohort size

    await emit(campaign_id, "optimizer", "agent_thought",
               f"Analyzing results for optimization (iteration {iteration}/{max_iterations})...")

    open_rate = metrics.get("open_rate", 0)
    click_rate = metrics.get("click_rate", 0)
    per_campaign = metrics.get("per_campaign", [])
    analysis = metrics.get("analysis", "")

    await emit(campaign_id, "optimizer", "agent_thought",
               f"Current scores: Open {open_rate:.1%} | Click {click_rate:.1%}")

    # ── Identify winning variant ──────────────────────────────────────────────
    winning_variant_info: dict = {}
    best_click = -1.0
    for i, email in enumerate(emails):
        if i < len(external_ids):
            ext_id = external_ids[i]
            for pc in per_campaign:
                if pc.get("external_campaign_id") == ext_id:
                    if pc.get("click_rate", 0) > best_click:
                        best_click = pc.get("click_rate", 0)
                        winning_variant_info = {
                            "variant": email.get("variant", ""),
                            "subject": email.get("subject", ""),
                            "body_excerpt": email.get("body", "")[:200],
                            "tone": email.get("tone", "professional"),
                            "send_time": email.get("send_time", ""),
                            "click_rate": pc.get("click_rate", 0),
                            "open_rate": pc.get("open_rate", 0),
                        }

    if winning_variant_info:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🏆 Winning variant: '{winning_variant_info['subject'][:70]}' "
                   f"— Click {winning_variant_info['click_rate']:.1%}")

    # ── Find customers who did NOT click (underperformers) ────────────────────
    underperforming_customer_ids: list = []
    try:
        raw_reports = get_reports_by_external_ids(external_ids)
        customer_ec: dict = {}
        for rpt in raw_reports:
            for row in rpt.get("raw_report", {}).get("data", []):
                cid = row.get("customer_id")
                if cid:
                    customer_ec[cid] = row.get("EC", "N")

        all_sent: list = []
        for email in emails:
            all_sent.extend(email.get("customer_ids", []))

        # Deduplicate preserving order
        seen: set = set()
        unique_sent: list = []
        for cid in all_sent:
            if cid not in seen:
                seen.add(cid)
                unique_sent.append(cid)

        underperforming_customer_ids = [
            cid for cid in unique_sent if customer_ec.get(cid, "N") == "N"
        ]
        converted = len(unique_sent) - len(underperforming_customer_ids)
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🎯 {len(underperforming_customer_ids)} non-clickers identified "
                   f"({converted} already converted — will NOT be re-sent to).")
    except Exception as e:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"⚠️ Could not compute underperformers: {str(e)[:60]}. Will use full cohort.")

    # ── Cohort coverage check ─────────────────────────────────────────────────
    all_customer_ids = set(c["customer_id"] for c in state.get("customers", []))
    all_emailed = set(state.get("all_emailed_customer_ids", []))
    uncovered = all_customer_ids - all_emailed
    coverage_note = ""

    if uncovered:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"⚠️ {len(uncovered)}/{len(all_customer_ids)} customers never emailed! "
                   f"Merging into rescue pool for next iteration.")
        # Uncovered customers get priority — prepend them before non-clickers
        uncovered_list = list(uncovered)
        underperforming_customer_ids = uncovered_list + [
            cid for cid in underperforming_customer_ids if cid not in uncovered
        ]
        coverage_note = (
            f"CRITICAL: {len(uncovered)} customers never emailed — cover them FIRST "
            f"using the winning variant style. "
        )

    # ── Stop conditions ───────────────────────────────────────────────────────
    base_return = {
        "winning_variant_info": winning_variant_info,
        "underperforming_customer_ids": underperforming_customer_ids,
    }

    # Check if we should stop
    if iteration >= max_iterations:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"✅ Reached max iterations ({max_iterations}). Campaign complete.")
        return {**base_return, "status": "done", "optimization_notes": "Max iterations reached"}

    # New scoring: maximize absolute EC=Y and EO=Y counts (1000-customer cohort)
    # EC (click) weighted 70%, EO (open) weighted 30%
    clicks_abs = int(round(click_rate * metrics.get("total_sent", 0)))
    opens_abs  = int(round(open_rate  * metrics.get("total_sent", 0)))

    await emit(campaign_id, "optimizer", "agent_thought",
               f"📊 Absolute counts: {clicks_abs} clicks / {opens_abs} opens out of {total_cohort} cohort")

    # Stop only if we've covered the whole cohort AND click count is strong
    cohort_coverage = len(all_emailed) / total_cohort if total_cohort > 0 else 0
    if cohort_coverage >= 0.99 and click_rate >= 0.40:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🏆 Full cohort covered ({len(all_emailed)}/{total_cohort}) "
                   f"with {click_rate:.1%} click rate. Stopping.")
        return {**base_return, "status": "done",
                "optimization_notes": f"Full cohort covered. Clicks={clicks_abs}, Opens={opens_abs}"}

    # If all customers already clicked, nothing left to rescue
    if len(underperforming_customer_ids) == 0 and len(emails) > 0 and customer_ec:
        await emit(campaign_id, "optimizer", "agent_thought",
                   "🏆 All sent customers have clicked. Stopping.")
        return {**base_return, "status": "done", "optimization_notes": "All customers converted"}

    # ── LLM strategy for next iteration ──────────────────────────────────────
    llm = get_llm(temperature=0.5)

    n_underperform = len(underperforming_customer_ids) if underperforming_customer_ids else metrics.get("total_sent", 0)

    per_campaign_summary = json.dumps([
        {k: v for k, v in pc.items() if k != "customer_ids"}
        for pc in per_campaign
    ], indent=2)
    exploit_instruction = (
        "EXPLOIT MODE: replicate the winning variant approach with minor subject tweaks only."
        if iteration >= 3
        else "Explore different tones and subject formats."
    )

    prompt = f"""You are a campaign optimization expert for SuperBFSI's XDeposit campaign.

Current Results (Iteration {iteration}/{max_iterations}):
- Open Rate: {open_rate:.1%} → {opens_abs} customers opened (target: maximize EO=Y count)
- Click Rate: {click_rate:.1%} → {clicks_abs} customers clicked (target: maximize EC=Y count, weighted 70%)
- Total Sent: {metrics.get('total_sent', 0)}
- Non-clickers to rescue next: {n_underperform}
- Cohort coverage: {len(all_emailed)}/{total_cohort} customers reached ({cohort_coverage:.0%})
- PRIORITY: Cover ALL 1000 customers at least once before optimizing re-sends
{coverage_note}
Best Performing Variant:
- Subject: "{winning_variant_info.get('subject', 'N/A')}"
- Tone: {winning_variant_info.get('tone', 'N/A')}
- Click Rate: {winning_variant_info.get('click_rate', 0):.1%}
- Body excerpt: "{winning_variant_info.get('body_excerpt', 'N/A')}"

Performance Analysis: {analysis}

Per-Campaign Breakdown:
{per_campaign_summary}

CRITICAL RULES:
1. BANNED: Do NOT use urgency, scarcity, or FOMO framing — the API penalizes this.
2. Preferred tones: trust-building, aspirational, informational, warm/personal.
3. {exploit_instruction}

Next iteration will re-target the {n_underperform} non-clickers/uncovered customers.
Provide specific instructions for the rescue send to maximise click rate.

Return ONLY this JSON:
{{
    "should_continue": true,
    "optimization_notes": "Tone/angle/content strategy for the rescue send",
    "subject_line_strategy": "Specific format to try: question / number-led / personalised (NOT urgency)",
    "content_adjustments": "What to change in the email body to drive more clicks",
    "timing_adjustments": "Best send time for non-clickers (morning / evening / night)"
}}"""

    try:
        content = await invoke_with_retry(llm, prompt)
        result = json.loads(clean_llm_json(content), strict=False)

        should_continue = result.get("should_continue", True)
        notes = result.get("optimization_notes", "")
        subject_strategy = result.get("subject_line_strategy", "")
        content_adj = result.get("content_adjustments", "")
        timing_adj = result.get("timing_adjustments", "")

        full_notes = (
            f"{coverage_note}"
            f"Iter {iteration} winner: subject='{winning_variant_info.get('subject', '')}' "
            f"tone={winning_variant_info.get('tone', '')} "
            f"click={winning_variant_info.get('click_rate', 0):.1%}. "
            f"Rescue {n_underperform} non-clickers. "
            f"Strategy: {notes}. "
            f"Subject format to try: {subject_strategy}. "
            f"Content: {content_adj}. Timing: {timing_adj}."
        )

        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🔧 Rescue strategy: {notes}")
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"📝 Subject format: {subject_strategy}")

        if not should_continue:
            await emit(campaign_id, "optimizer", "agent_thought",
                       "✅ Optimizer: performance acceptable. Stopping.")
            return {**base_return, "status": "done", "optimization_notes": full_notes}

        increment_campaign_iteration(campaign_id)

        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🔄 Launching rescue iteration {iteration + 1} "
                   f"({n_underperform} non-clickers only)...")

        return {
            **base_return,
            "iteration": iteration + 1,
            "optimization_notes": full_notes,
            "rejection_reason": None,
            "status": "optimizing",
        }

    except Exception as e:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"⚠️ Optimizer fallback: {str(e)[:80]}. Stopping.")
        return {**base_return, "status": "done",
                "optimization_notes": f"Optimizer error: {str(e)}"}
