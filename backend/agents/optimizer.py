"""
optimizer.py — Analyse results and decide next iteration strategy.

Issues fixed in this rewrite:
  1. LLM no longer controls loop continuation. should_continue removed from
     LLM prompt entirely. Only 3 hard conditions stop the loop:
       a) iteration >= max_iterations
       b) full cohort coverage AND click_rate >= 0.50
       c) zero rescuable customers remaining
  2. Winning variant identified by external_campaign_id match, not fragile
     array index pairing that breaks when sends fail.
  3. Optimizer uses per-iteration click_rate from monitor (not cumulative)
     so stop decisions reflect actual current performance.
  4. Rescue strategy correctly separates Bucket A (opened, didn't click)
     from Bucket B (never opened) — each gets a different fix directive.
  5. Re-target cap: Bucket B customers dropped after iteration 3 to stop
     wasting API calls on cold customers.
"""

import json
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json, invoke_with_retry
from db.database import increment_campaign_iteration, get_reports_by_external_ids

# After this many iterations, permanently drop never-opened customers
BUCKET_B_DROP_AFTER = 3


async def optimizer_node(state: CampaignState) -> dict:
    campaign_id   = state["campaign_id"]
    metrics       = state.get("metrics", {})
    emails        = state.get("emails", [])
    external_ids  = state.get("external_campaign_ids", [])
    iteration     = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 5)
    total_cohort  = 1000

    await emit(campaign_id, "optimizer", "agent_thought",
               f"Analysing results (iteration {iteration}/{max_iterations})...")

    # Use per-iteration rates — NOT cumulative — for stop decisions
    open_rate    = metrics.get("open_rate", 0)
    click_rate   = metrics.get("click_rate", 0)
    per_campaign = metrics.get("per_campaign", [])
    analysis     = metrics.get("analysis", "")

    await emit(campaign_id, "optimizer", "agent_thought",
               f"Iteration {iteration} — Open {open_rate:.1%} | Click {click_rate:.1%}")

    # ── Identify winning variant by external_campaign_id ─────────────────────
    # FIX: Match by ID not by index. Index matching breaks when any send fails.
    winning_variant_info: dict = {}
    best_click = -1.0

    # Build external_id → email lookup
    ext_to_email: dict = {}
    for email in emails:
        ext_id = email.get("external_campaign_id", "")
        if ext_id:
            ext_to_email[ext_id] = email

    for pc in per_campaign:
        ext_id    = pc.get("external_campaign_id", "")
        pc_click  = pc.get("click_rate", 0)
        if pc_click > best_click:
            best_click = pc_click
            email_meta = ext_to_email.get(ext_id, {})
            winning_variant_info = {
                "variant":      email_meta.get("variant", ""),
                "subject":      email_meta.get("subject", pc.get("subject", "")),
                "body_excerpt": email_meta.get("body", "")[:200],
                "tone":         email_meta.get("tone", pc.get("tone", "informational, friendly")),
                "send_time":    email_meta.get("send_time", ""),
                "click_rate":   pc_click,
                "open_rate":    pc.get("open_rate", 0),
                "external_campaign_id": ext_id,
            }

    if winning_variant_info:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🏆 Winner: '{winning_variant_info.get('subject','')[:70]}' "
                   f"— Click {winning_variant_info['click_rate']:.1%} | "
                   f"Open {winning_variant_info['open_rate']:.1%}")

    # ── Identify non-clickers and bucket them ─────────────────────────────────
    all_converted: set = set(state.get("all_converted_customer_ids", []))
    customer_ec: dict  = {}
    customer_eo: dict  = {}

    try:
        raw_reports = get_reports_by_external_ids(external_ids)
        for rpt in raw_reports:
            for row in rpt.get("raw_report", {}).get("data", []):
                cid = row.get("customer_id")
                if cid:
                    customer_ec[cid] = row.get("EC", "N")
                    customer_eo[cid] = row.get("EO", "N")

        converters_this_iter = {cid for cid, v in customer_ec.items() if v == "Y"}
        all_converted = all_converted | converters_this_iter

        # All customers sent to this iteration
        all_sent_this_iter: list[str] = []
        seen: set = set()
        for email in emails:
            for cid in email.get("customer_ids", []):
                if cid not in seen:
                    all_sent_this_iter.append(cid)
                    seen.add(cid)

        # Bucket A: opened but did not click — body/CTA fix needed
        bucket_a = [
            cid for cid in all_sent_this_iter
            if customer_eo.get(cid) == "Y"
            and customer_ec.get(cid) == "N"
            and cid not in all_converted
        ]

        # Bucket B: never opened — subject fix needed
        # Drop after BUCKET_B_DROP_AFTER iterations (cold customers)
        bucket_b = []
        if iteration < BUCKET_B_DROP_AFTER:
            bucket_b = [
                cid for cid in all_sent_this_iter
                if customer_eo.get(cid) == "N"
                and customer_ec.get(cid) == "N"
                and cid not in all_converted
            ]
        else:
            dropped = len([
                cid for cid in all_sent_this_iter
                if customer_eo.get(cid) == "N" and customer_ec.get(cid) == "N"
            ])
            if dropped > 0:
                await emit(campaign_id, "optimizer", "agent_thought",
                           f"🗑️ Iteration {iteration}: dropping {dropped} permanently cold "
                           f"customers (never opened after {BUCKET_B_DROP_AFTER - 1} attempts).")

        converted_count = len(converters_this_iter)
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"✅ {converted_count} converted | "
                   f"Bucket A (opened, no click): {len(bucket_a)} | "
                   f"Bucket B (never opened): {len(bucket_b)}")
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🔒 {len(all_converted)} total converters excluded permanently.")

        # Combined rescue pool: A first (higher chance of converting), then B
        underperforming_customer_ids = bucket_a + bucket_b

    except Exception as e:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"⚠️ Could not compute underperformers: {str(e)[:80]}. Using full cohort.")
        bucket_a = []
        bucket_b = []
        underperforming_customer_ids = []

    # ── Coverage check ────────────────────────────────────────────────────────
    all_customer_ids = {c["customer_id"] for c in state.get("customers", [])}
    all_emailed      = set(state.get("all_emailed_customer_ids", []))
    uncovered        = all_customer_ids - all_emailed - all_converted
    coverage_note    = ""

    if uncovered:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"⚠️ {len(uncovered)} customers never emailed — adding to rescue pool.")
        # Uncovered customers take priority over known non-clickers
        underperforming_customer_ids = list(uncovered) + [
            cid for cid in underperforming_customer_ids if cid not in uncovered
        ]
        coverage_note = (
            f"PRIORITY: {len(uncovered)} customers have never been emailed. "
            f"Cover them first using the winning variant style.\n"
        )

    cohort_coverage = len(all_emailed) / total_cohort if total_cohort > 0 else 0
    clicks_abs      = int(round(click_rate * metrics.get("total_sent", 0)))
    opens_abs       = int(round(open_rate  * metrics.get("total_sent", 0)))

    await emit(campaign_id, "optimizer", "agent_thought",
               f"📊 Coverage: {len(all_emailed)}/{total_cohort} ({cohort_coverage:.0%}) | "
               f"Clicks: {clicks_abs} | Opens: {opens_abs}")

    # ── Base return dict ──────────────────────────────────────────────────────
    base_return = {
        "winning_variant_info":         winning_variant_info,
        "underperforming_customer_ids": underperforming_customer_ids,
        "all_converted_customer_ids":   list(all_converted),
    }

    # ── HARD stop conditions — LLM has NO say in these ───────────────────────
    # 1. Max iterations reached
    if iteration >= max_iterations:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"✅ Max iterations ({max_iterations}) reached. Campaign complete.")
        return {**base_return, "status": "done",
                "optimization_notes": "Max iterations reached"}

    # 2. Full cohort covered with strong click rate
    if cohort_coverage >= 0.99 and click_rate >= 0.50:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🏆 Full cohort covered with {click_rate:.1%} click rate. Stopping.")
        return {**base_return, "status": "done",
                "optimization_notes": f"Full cohort covered. Clicks={clicks_abs}"}

    # 3. Nothing left to rescue
    if not underperforming_customer_ids and customer_ec:
        await emit(campaign_id, "optimizer", "agent_thought",
                   "🏆 No rescuable customers remain. Campaign complete.")
        return {**base_return, "status": "done",
                "optimization_notes": "All customers converted or cold-dropped"}

    # ── LLM strategy for next iteration ──────────────────────────────────────
    llm = get_llm(temperature=0.5)

    exploit_instruction = (
        "EXPLOIT MODE: replicate the winning variant tone and subject format with minor wording tweaks."
        if iteration >= 2
        else "EXPLORE MODE: try two different angles and tones."
    )

    bucket_a_note = (
        f"Bucket A ({len(bucket_a)} customers — opened but did not click):\n"
        f"  Subject worked. Fix: move CTA to sentence 1, cut body to 80 words max.\n"
    ) if bucket_a else ""

    bucket_b_note = (
        f"Bucket B ({len(bucket_b)} customers — never opened):\n"
        f"  Subject failed. Fix: completely different subject format and emotional hook.\n"
    ) if bucket_b else ""

    per_campaign_summary = json.dumps([
        {k: v for k, v in pc.items() if k != "customer_ids"}
        for pc in per_campaign
    ], indent=2)

    prompt = f"""You are a campaign optimisation expert for SuperBFSI XDeposit.

Iteration {iteration}/{max_iterations} results:
- Open Rate:  {open_rate:.1%} ({opens_abs} customers)
- Click Rate: {click_rate:.1%} ({clicks_abs} customers) ← weighted 70% in scoring
- Total Sent: {metrics.get('total_sent', 0)}
- Cohort coverage: {len(all_emailed)}/{total_cohort} ({cohort_coverage:.0%})
{coverage_note}
Best Performing Variant:
- Subject: "{winning_variant_info.get('subject', 'N/A')}"
- Tone:    {winning_variant_info.get('tone', 'N/A')}
- Click Rate: {winning_variant_info.get('click_rate', 0):.1%}
- Open Rate:  {winning_variant_info.get('open_rate', 0):.1%}

Non-clicker breakdown for rescue:
{bucket_a_note}{bucket_b_note}
Performance Analysis: {analysis}

Per-Campaign Breakdown:
{per_campaign_summary}

Instruction: {exploit_instruction}

RULES:
- BANNED: urgency, scarcity, FOMO — API penalises these
- Preferred tones: trust-building, aspirational, informational, warm/personal
- Provide SPECIFIC, ACTIONABLE instructions — not generic advice

Return ONLY this JSON (no markdown):
{{
    "optimization_notes": "Overall strategy for next iteration",
    "subject_line_strategy": "Exact format: question / number-led / statement + example wording",
    "content_adjustments": "Specific body changes: word count, CTA position, benefit framing",
    "timing_adjustments": "Best send time: morning / afternoon / evening / night"
}}"""

    try:
        content          = await invoke_with_retry(llm, prompt)
        result           = json.loads(clean_llm_json(content), strict=False)
        notes            = result.get("optimization_notes", "")
        subject_strategy = result.get("subject_line_strategy", "")
        content_adj      = result.get("content_adjustments", "")
        timing_adj       = result.get("timing_adjustments", "")

        full_notes = (
            f"{coverage_note}"
            f"Winner: subject='{winning_variant_info.get('subject','')}' "
            f"tone='{winning_variant_info.get('tone','')}' "
            f"click={winning_variant_info.get('click_rate',0):.1%}. "
            f"Bucket A ({len(bucket_a)} openers): CTA-first fix. "
            f"Bucket B ({len(bucket_b)} non-openers): new subject format. "
            f"Strategy: {notes}. "
            f"Subject: {subject_strategy}. "
            f"Body: {content_adj}. "
            f"Timing: {timing_adj}."
        )

        await emit(campaign_id, "optimizer", "agent_thought",
                   f"🔧 Strategy: {notes[:120]}")
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"📝 Subject format: {subject_strategy[:80]}")

    except Exception as e:
        await emit(campaign_id, "optimizer", "agent_thought",
                   f"⚠️ Optimizer LLM failed ({str(e)[:80]}). Using safe defaults.")
        full_notes       = f"{coverage_note}Replicate winning tone. Improve CTA position."
        subject_strategy = "question format — ask about their current FD earnings"
        content_adj      = "CTA in sentence 1, cut to 80 words"
        timing_adj       = "morning"

    increment_campaign_iteration(campaign_id)

    await emit(campaign_id, "optimizer", "agent_thought",
               f"🔄 Launching iteration {iteration + 1} "
               f"({len(underperforming_customer_ids)} customers to rescue)...")

    return {
        **base_return,
        "iteration":               iteration + 1,
        "optimization_notes":      full_notes,
        "opt_subject_strategy":    subject_strategy,
        "opt_content_adjustments": content_adj,
        "rejection_reason":        None,
        "status":                  "optimizing",
    }