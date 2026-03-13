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
    emails      = state.get("emails", [])
    external_ids = state.get("external_campaign_ids", [])
    iteration   = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 5)
    all_emailed = state.get("all_emailed_customer_ids", [])
    all_converted = set(state.get("all_converted_customer_ids", []))

    await emit(campaign_id, "optimizer", "agent_thought",
               f"🔍 Analyzing results for iteration {iteration}/{max_iterations}...")

    open_rate  = metrics.get("open_rate", 0)
    click_rate = metrics.get("click_rate", 0)
    per_campaign = metrics.get("per_campaign", [])
    analysis   = metrics.get("analysis", "")

    await emit(campaign_id, "optimizer", "agent_thought",
               f"📊 Open {open_rate:.1%} | Click {click_rate:.1%} | "
               f"Sent {metrics.get('total_sent', 0)} | Emailed so far: {len(all_emailed)}")

    # ── Identify winning variant ───────────────────────────────────────────────
    winning_variant_info: dict = {}
    best_click = -1.0
    for i, email in enumerate(emails):
        if i < len(external_ids):
            for pc in per_campaign:
                if pc.get("external_campaign_id") == external_ids[i]:
                    if pc.get("click_rate", 0) > best_click:
                        best_click = pc["click_rate"]
                        winning_variant_info = {
                            "variant":      email.get("variant", ""),
                            "subject":      email.get("subject", ""),
                            "body_excerpt": email.get("body", "")[:200],
                            "tone":         email.get("tone", "professional"),
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

    # ── Smart non-clicker segmentation ────────────────────────────────────────
    # Bucket 1: Opened but didn't click → body/CTA problem
    opened_not_clicked = [
        cid for cid in opened_ids
        if cid not in clicked_ids and cid not in all_converted
    ]
    # Bucket 2: Never opened → subject problem
    emailed_set = set(all_emailed)
    never_opened = [
        cid for cid in emailed_set
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

    # ── Stop conditions ────────────────────────────────────────────────────────
    # With 1000-customer cohort, scoring is absolute EC=Y + EO=Y count
    total_cohort   = 1000
    clicks_abs     = len(all_converted)
    coverage_pct   = len(emailed_set) / total_cohort

    base_return = {
        "winning_variant_info":       winning_variant_info,
        "underperforming_customer_ids": opened_not_clicked + never_opened,
        "all_converted_customer_ids": list(all_converted),
    }

    if iteration >= max_iterations:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"✅ Max iterations ({max_iterations}) reached. "
                   f"Final: {clicks_abs} clicks, {len(opened_ids)} opens, "
                   f"coverage {coverage_pct:.0%}.")
        return {**base_return, "status": "done",
                "optimization_notes": f"Max iterations. clicks={clicks_abs}"}

    if len(opened_not_clicked) == 0 and len(never_opened) == 0:
        await emit(campaign_id, "optimizer", "agent_thought",
                   "🏆 No rescuable customers left. Stopping.")
        return {**base_return, "status": "done",
                "optimization_notes": "All reachable customers converted or dropped"}

    # ── Cold-pool stop: tiny rescue pool isn't worth another API round ────────
    total_rescuable = len(opened_not_clicked) + len(never_opened)
    if total_rescuable < 50:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🛑 Only {total_rescuable} rescuable customers remain (<50). "
                   f"Not worth another API spend. Stopping.")
        return {**base_return, "status": "done",
                "optimization_notes": f"Rescue pool too small ({total_rescuable}). Stopping."}

    # ── Coverage + click-rate hard stop (PS compliance) ───────────────────────
    # PS scores on absolute EC=Y + EO=Y counts — no reason to burn extra API
    # calls once we've hit the entire cohort AND a solid click rate.
    if coverage_pct >= 0.99 and click_rate >= 0.20:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"✅ Coverage {coverage_pct:.0%} + click rate {click_rate:.1%} ≥ 20% — "
                   f"target hit ({clicks_abs} absolute clicks). Stopping.")
        return {**base_return, "status": "done",
                "optimization_notes": (
                    f"Coverage+click target met. "
                    f"clicks={clicks_abs}, coverage={coverage_pct:.0%}, ctr={click_rate:.1%}"
                )}

    # ── LLM strategy — split by bucket ────────────────────────────────────────
    llm = get_llm(temperature=0.5)

    # Current-iteration rates (from per_campaign, which is always this iteration only)
    iter_sent   = sum(pc.get("total_sent", 0) for pc in per_campaign)
    iter_opens  = sum(pc.get("open_rate",  0) * pc.get("total_sent", 0) for pc in per_campaign)
    iter_clicks = sum(pc.get("click_rate", 0) * pc.get("total_sent", 0) for pc in per_campaign)
    iter_open_rate  = round(iter_opens  / iter_sent, 4) if iter_sent > 0 else open_rate
    iter_click_rate = round(iter_clicks / iter_sent, 4) if iter_sent > 0 else click_rate

    prompt = f"""You are an email campaign optimizer for SuperBFSI's XDeposit term deposit.

ITERATION: {iteration}/{max_iterations}
THIS ITERATION RESULTS (current send only):
  - Open rate: {iter_open_rate:.1%}  |  Click rate: {iter_click_rate:.1%}  |  Sent: {iter_sent}
CUMULATIVE RESULTS (all iterations):
  - Open rate: {open_rate:.1%}  |  Click rate: {click_rate:.1%}
  - Absolute clicks (EC=Y): {clicks_abs}  |  Cohort coverage: {coverage_pct:.0%} of 1000
  - Winning subject: "{winning_variant_info.get('subject', 'N/A')}"
  - Winning tone: {winning_variant_info.get('tone', 'N/A')}

NON-CLICKER SEGMENTATION:
  Bucket A — Opened but didn't click: {len(opened_not_clicked)} customers
    → They SAW the subject and opened. The body/CTA failed them.
    → Fix: Move CTA to line 1. Add specific ₹ benefit. Cut body by 50%.
  Bucket B — Never opened: {len(never_opened)} customers
    → The subject didn't grab them.
    → Fix: Completely different subject format. If we used statement → try question.
           If we used number → try personalised. Try emoji in subject.

BANNED: urgency, scarcity, FOMO, pressure. API PENALISES these.
ALLOWED: trust-building, aspirational, informational, warm/personal.

Return ONLY this JSON:
{{
  "bucket_a_subject_strategy": "specific subject format for opened-not-clicked (keep similar to winner since they DID open)",
  "bucket_a_body_strategy": "specific body fix — what to change to get them to click",
  "bucket_b_subject_strategy": "completely different subject format for never-opened",
  "bucket_b_body_strategy": "body strategy for never-opened",
  "should_continue": true,
  "optimization_notes": "one line summary"
}}"""

    try:
        content = await invoke_with_retry(llm, prompt)
        result  = json.loads(clean_llm_json(content))

        should_continue = result.get("should_continue", True)
        notes = result.get("optimization_notes", "")

        # Build separate strategy strings for each bucket
        # These get passed into state and used by strategist/content_gen
        bucket_a_strategy = (
            f"OPENED-NOT-CLICKED RESCUE ({len(opened_not_clicked)} customers):\n"
            f"  Subject: {result.get('bucket_a_subject_strategy', 'Keep similar to winner — they opened it')}\n"
            f"  Body: {result.get('bucket_a_body_strategy', 'Move CTA to line 1. Cut to 80 words max.')}"
        )
        bucket_b_strategy = (
            f"NEVER-OPENED RESCUE ({len(never_opened)} customers):\n"
            f"  Subject: {result.get('bucket_b_subject_strategy', 'Completely different format from previous')}\n"
            f"  Body: {result.get('bucket_b_body_strategy', 'Short. Lead with benefit in line 1.')}"
        )

        full_notes = (
            f"iter={iteration} | clicks={clicks_abs} | coverage={coverage_pct:.0%}\n"
            f"Bucket A ({len(opened_not_clicked)} openers): {bucket_a_strategy[:120]}\n"
            f"Bucket B ({len(never_opened)} cold): {bucket_b_strategy[:120]}\n"
            f"LLM: {notes}"
        )

        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🔧 Bucket A strategy: {result.get('bucket_a_subject_strategy', '')[:80]}")
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🔧 Bucket B strategy: {result.get('bucket_b_subject_strategy', '')[:80]}")

        if not should_continue:
            return {**base_return, "status": "done", "optimization_notes": full_notes}

        increment_campaign_iteration(campaign_id)

        return {
            **base_return,
            "iteration":               iteration + 1,
            "optimization_notes":      full_notes,
            "opt_subject_strategy":    result.get("bucket_b_subject_strategy", ""),   # for never-opened
            "opt_content_adjustments": result.get("bucket_a_body_strategy", ""),      # for opened-not-clicked
            "rejection_reason":        None,
            "status":                  "optimizing",
        }

    except Exception as e:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"⚠️ Optimizer error: {str(e)[:80]}. Stopping.")
        return {**base_return, "status": "done",
                "optimization_notes": f"Optimizer error: {str(e)}"}