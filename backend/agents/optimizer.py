"""
Optimizer Node — Fixed for 1000-customer final round.

KEY CHANGES:
1. Segments non-clickers into "opened-not-clicked" vs "never-opened" — different strategies
2. Caps re-targeting at MAX_RETARGET_COUNT per customer — stops wasting calls on cold leads
3. Passes specific per-bucket strategy to strategist/content_gen instead of generic notes
"""

import json
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json, invoke_with_retry
from db.database import (
    increment_campaign_iteration,
    get_reports_by_external_ids,
    record_customer_report_events,
    get_customer_lifecycle_stats,
)

# ── After this many emails with no response, drop the customer ────────────────
MAX_RETARGET_COUNT = 3   # customer emailed 3+ times with no click → stop targeting


async def optimizer_node(state: CampaignState) -> dict:
    campaign_id = state["campaign_id"]
    metrics     = state.get("metrics", {})
    customers   = state.get("customers", [])
    emails      = state.get("emails", [])
    external_ids = state.get("external_campaign_ids", [])
    iteration   = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 5)
    all_emailed = state.get("all_emailed_customer_ids", [])
    all_converted = set(state.get("all_converted_customer_ids", []))

    await emit(campaign_id, "optimizer", "agent_thought",
               f"🔍 Analyzing results for iteration {iteration}/{max_iterations}...")

    cumulative_open_rate = metrics.get("open_rate", 0)
    cumulative_click_rate = metrics.get("click_rate", 0)
    current_open_rate = metrics.get("current_open_rate", cumulative_open_rate)
    current_click_rate = metrics.get("current_click_rate", cumulative_click_rate)
    per_campaign = metrics.get("per_campaign", [])
    analysis   = metrics.get("analysis", "")

    await emit(campaign_id, "optimizer", "agent_thought",
               f"📊 This iteration: Open {current_open_rate:.1%} | Click {current_click_rate:.1%} | "
               f"Sent {sum(pc.get('total_sent', 0) for pc in per_campaign)} | "
               f"Cumulative emailed: {len(all_emailed)}")

    # ── Identify winning variant ───────────────────────────────────────────────
    winning_variant_info: dict = {}
    best_click = -1.0
    email_by_ext_id: dict[str, dict] = {}
    for email in emails:
        ext_id = str(email.get("external_campaign_id", "")).strip()
        if ext_id:
            email_by_ext_id[ext_id] = email
    for i, ext_id in enumerate(external_ids):
        if ext_id and ext_id not in email_by_ext_id and i < len(emails):
            email_by_ext_id[ext_id] = emails[i]

    for pc in per_campaign:
        ext_id = pc.get("external_campaign_id")
        email = email_by_ext_id.get(ext_id, {})
        if pc.get("click_rate", 0) > best_click:
            best_click = pc.get("click_rate", 0)
            winning_variant_info = {
                "variant":      email.get("variant", pc.get("variant", "")),
                "subject":      email.get("subject", pc.get("subject", "")),
                "body_excerpt": email.get("body", "")[:200],
                "tone":         email.get("tone", pc.get("tone", "professional")),
                "click_rate":   pc.get("click_rate", 0),
                "open_rate":    pc.get("open_rate", 0),
            }

    if winning_variant_info:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🏆 Winner: '{winning_variant_info['subject'][:60]}' "
                   f"— click {winning_variant_info['click_rate']:.1%}")

    # ── Fetch raw report rows to separate opens vs non-openers ────────────────
    # get_reports_by_external_ids returns [{external_campaign_id, raw_report}]
    # Per-customer rows are nested inside raw_report["data"]
    all_report_rows: list[dict] = []
    for pc in per_campaign:
        ext_id = pc.get("external_campaign_id")
        if ext_id:
            db_rows = get_reports_by_external_ids([ext_id])
            for db_row in (db_rows if isinstance(db_rows, list) else []):
                # Each db_row = {"external_campaign_id": ..., "raw_report": {"data": [...]}}
                customer_rows = db_row.get("raw_report", {}).get("data", [])
                all_report_rows.extend(customer_rows)

    # Build sets from per-customer rows
    opened_ids:  set[str] = set()
    clicked_ids: set[str] = set()
    for customer_row in all_report_rows:
        cid = customer_row.get("customer_id", "")
        if not cid:
            continue
        if str(customer_row.get("EO", "N")).upper() == "Y":
            opened_ids.add(cid)
        if str(customer_row.get("EC", "N")).upper() == "Y":
            clicked_ids.add(cid)

    # Persist EO/EC outcomes for this iteration and update converted set
    record_customer_report_events(campaign_id, iteration, all_report_rows)
    all_converted.update(clicked_ids)
    customer_stats = get_customer_lifecycle_stats(campaign_id)

    current_iteration_customer_ids: set[str] = set()
    for pc in per_campaign:
        current_iteration_customer_ids.update(pc.get("customer_ids", []))
    if not current_iteration_customer_ids:
        for ext_id in external_ids:
            email = email_by_ext_id.get(ext_id, {})
            current_iteration_customer_ids.update(email.get("customer_ids", []))

    # ── Smart non-clicker segmentation ────────────────────────────────────────
    # Bucket 1: Opened but didn't click → body/CTA problem
    opened_not_clicked = [
        cid for cid in opened_ids
        if cid in current_iteration_customer_ids and cid not in clicked_ids and cid not in all_converted
    ]
    # Bucket 2: Never opened → subject problem
    never_opened = [
        cid for cid in current_iteration_customer_ids
        if cid not in opened_ids and cid not in all_converted
    ]

    await emit(campaign_id, "optimizer", "agent_thought",
               f"📂 Segmented non-clickers:")
    await emit(campaign_id, "optimizer", "agent_thought",
               f"   • Opened but didn't click: {len(opened_not_clicked)} → body/CTA fix needed")
    await emit(campaign_id, "optimizer", "agent_thought",
               f"   • Never opened: {len(never_opened)} → subject fix needed")
    await emit(campaign_id, "optimizer", "agent_thought",
               f"   • Converted (EC=Y, skip forever): {len(all_converted)}")

    # ── Re-target cap: drop permanently cold customers using real customer history ───────
    # Rule: from iteration 3 onward, remove customers who have already been emailed
    # 2+ times and have NEVER opened even once.
    if iteration >= MAX_RETARGET_COUNT:
        permanently_cold = [
            cid for cid in never_opened
            if customer_stats.get(cid, {}).get("sent_count", 0) >= 2
            and customer_stats.get(cid, {}).get("opened_count", 0) == 0
        ]
        cold_set = set(permanently_cold)
        never_opened = [
            cid for cid in never_opened
            if cid not in cold_set
        ]
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🗑️ Dropped {len(permanently_cold)} permanently cold customers "
                   f"(never opened after 2 attempts).")

    iter_sent = sum(pc.get("total_sent", 0) for pc in per_campaign)
    iter_opens_abs = sum(
        pc.get("opens", int(round(pc.get("open_rate", 0) * pc.get("total_sent", 0))))
        for pc in per_campaign
    )
    iter_clicks_abs = sum(
        pc.get("clicks", int(round(pc.get("click_rate", 0) * pc.get("total_sent", 0))))
        for pc in per_campaign
    )
    iter_open_rate = round(iter_opens_abs / iter_sent, 4) if iter_sent > 0 else current_open_rate
    iter_click_rate = round(iter_clicks_abs / iter_sent, 4) if iter_sent > 0 else current_click_rate

    # ── Stop conditions ───────────────────────────────────────────────────────
    # Only hard conditions are allowed to stop the autonomous loop:
    # max iterations, or no one left to rescue because all targeted customers converted.
    total_cohort = len(customers) or 1000
    underperforming_customer_ids = opened_not_clicked + never_opened

    base_return = {
        "winning_variant_info":         winning_variant_info,
        "underperforming_customer_ids": underperforming_customer_ids,
        "opened_not_clicked_customer_ids": opened_not_clicked,
        "never_opened_customer_ids":    never_opened,
        "all_converted_customer_ids":   list(all_converted),
    }

    # Hard cap — always respected
    if iteration >= max_iterations:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"✅ Reached max iterations ({max_iterations}). Campaign complete.")
        return {**base_return,
                "status": "done",
                "optimization_notes": "Max iterations reached"}

    coverage_pct = len(all_emailed) / total_cohort if total_cohort > 0 else 0

    await emit(campaign_id, "optimizer", "agent_thought",
               f"📊 Coverage: {len(all_emailed)}/{total_cohort} ({coverage_pct:.0%}) | "
               f"Iteration clicks: {iter_clicks_abs} | Iteration opens: {iter_opens_abs}")

    # All customers converted — nothing left to rescue
    customer_ec = {
        cid: ("Y" if customer_stats.get(cid, {}).get("clicked_count", 0) > 0 else "N")
        for cid in all_emailed
    }
    if not underperforming_customer_ids and customer_ec:
        all_clicked = all(v == "Y" for v in customer_ec.values())
        if all_clicked:
            await emit(campaign_id, "optimizer", "agent_thought",
                       "🏆 All sent customers have clicked. Stopping.")
            return {**base_return,
                    "status": "done",
                    "optimization_notes": "All customers converted"}

    # ── LLM strategy — split by bucket ────────────────────────────────────────
    llm = get_llm(temperature=0.5)

    prompt = f"""You are an email campaign optimizer for SuperBFSI's XDeposit term deposit.

ITERATION: {iteration}/{max_iterations}
THIS ITERATION RESULTS (current send only):
  - Open rate: {iter_open_rate:.1%}  |  Click rate: {iter_click_rate:.1%}  |  Sent: {iter_sent}
CUMULATIVE RESULTS (all iterations):
  - Open rate: {cumulative_open_rate:.1%}  |  Click rate: {cumulative_click_rate:.1%}
  - Absolute clicks this iteration (EC=Y): {iter_clicks_abs}  |  Cohort coverage: {coverage_pct:.0%} of {total_cohort}
  - Winning subject: "{winning_variant_info.get('subject', 'N/A')}"
  - Winning tone: {winning_variant_info.get('tone', 'N/A')}

NON-CLICKER SEGMENTATION:
  Bucket A — Opened but didn't click: {len(opened_not_clicked)} customers
    → They SAW the subject and opened. The body/CTA failed them.
    → Fix: Keep the winning subject format and tone. Change the body/CTA only.
    → Start the CTA in sentence 1. Add a specific ₹ benefit. Cut body by 50%.
  Bucket B — Never opened: {len(never_opened)} customers
    → The subject didn't grab them.
    → Fix: Use a completely different subject format and a different tone/angle.
           If the winner was a statement, try a question. If it was a question, try number-led.

BANNED: urgency, scarcity, FOMO, pressure. API PENALISES these.
ALLOWED: trust-building, aspirational, informational, warm/personal.

Return ONLY this JSON:
{{
        "optimization_notes": "Tone/angle/content strategy for the rescue send",
        "subject_line_strategy": "Specific format: question / number-led / personalised (NOT urgency)",
        "content_adjustments": "What to change in the email body to drive more clicks",
        "timing_adjustments": "Best send time for non-clickers (morning / evening / night)"
}}"""

    try:
        content = await invoke_with_retry(llm, prompt)
        result  = json.loads(clean_llm_json(content))

        notes = result.get("optimization_notes", "")
        subject_strategy = result.get(
            "subject_line_strategy",
            "Completely different format from previous (no urgency)"
        )
        content_adj = result.get(
            "content_adjustments",
            "Move CTA to line 1. Cut to 80 words max."
        )
        timing_adj = result.get("timing_adjustments", "evening")

        # Build separate strategy strings for each bucket
        # These get passed into state and used by strategist/content_gen
        bucket_a_strategy = (
            f"OPENED-NOT-CLICKED RESCUE ({len(opened_not_clicked)} customers):\n"
            f"  Subject: {subject_strategy}\n"
            f"  Body: {content_adj}"
        )
        bucket_b_strategy = (
            f"NEVER-OPENED RESCUE ({len(never_opened)} customers):\n"
            f"  Subject: {subject_strategy}\n"
            f"  Body: {content_adj}"
        )
        n_underperform = len(underperforming_customer_ids)

        full_notes = (
            f"iter={iteration} | clicks={iter_clicks_abs} | coverage={coverage_pct:.0%}\n"
            f"Bucket A ({len(opened_not_clicked)} openers): {bucket_a_strategy[:120]}\n"
            f"Bucket B ({len(never_opened)} cold): {bucket_b_strategy[:120]}\n"
            f"Timing: {timing_adj}\n"
            f"LLM: {notes}"
        )

        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🔧 Subject strategy: {subject_strategy[:80]}")
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🔧 Content adjustments: {content_adj[:80]}")

        increment_campaign_iteration(campaign_id)

        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🔄 Launching rescue iteration {iteration + 1} "
                   f"({n_underperform} non-clickers only)...")

        return {
            **base_return,
            "iteration":              iteration + 1,
            "optimization_notes":     full_notes,
            "opt_subject_strategy":   subject_strategy,
            "opt_content_adjustments": content_adj,
            "rejection_reason":       None,
            "status":                 "optimizing",
        }

    except Exception as e:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"⚠️ Optimizer error: {str(e)[:80]}. Stopping.")
        return {**base_return, "status": "done",
                "optimization_notes": f"Optimizer error: {str(e)}"}
