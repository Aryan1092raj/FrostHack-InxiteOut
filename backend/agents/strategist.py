import json
from datetime import datetime, timedelta
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json, invoke_with_retry


def _detect_subject_format(subject: str) -> str:
    s = (subject or "").strip()
    if not s:
        return "unknown"
    if "?" in s:
        return "question"
    first_token = s.split()[0] if s.split() else ""
    if first_token[:1].isdigit() or first_token.startswith("₹"):
        return "number-led"
    return "statement"


def _split_evenly(customer_ids: list[str]) -> tuple[list[str], list[str]]:
    if len(customer_ids) <= 1:
        return customer_ids, []
    mid = len(customer_ids) // 2
    return customer_ids[:mid], customer_ids[mid:]


def _rescue_tones(winning_tone: str) -> tuple[str, str]:
    lowered = (winning_tone or "").lower()
    if "professional" in lowered or "analytical" in lowered or "trust" in lowered:
        return ("warm and personal", "problem-led and conversational")
    return ("analytical and trust-building", "professional and credibility-led")


def _append_strategy_note(variant: dict, note: str):
    note = (note or "").strip()
    if not note:
        return
    existing = str(variant.get("strategy_notes", "")).strip()
    variant["strategy_notes"] = f"{existing}\n{note}".strip() if existing else note


async def strategist_node(state: CampaignState) -> dict:
    campaign_id = state["campaign_id"]
    brief = state["brief"]
    segments = state["segments"]
    iteration = state.get("iteration", 1)
    optimization_notes = state.get("optimization_notes", "")
    rejection_reason = state.get("rejection_reason", "")
    underperforming_ids: list = state.get("underperforming_customer_ids", [])
    opened_not_clicked_ids: list = state.get("opened_not_clicked_customer_ids", [])
    never_opened_ids: list = state.get("never_opened_customer_ids", [])
    winning_variant_info: dict = state.get("winning_variant_info", {})

    await emit(campaign_id, "strategist", "agent_thought",
               f"Planning campaign strategy (iteration {iteration})...")

    if rejection_reason:
        await emit(campaign_id, "strategist", "agent_thought",
                   f"Incorporating rejection feedback: {rejection_reason}")

    if optimization_notes and iteration > 1:
        await emit(campaign_id, "strategist", "agent_thought",
                   f"Optimization context: {optimization_notes[:120]}...")

    # For iteration 2+, rescue only the non-clickers — don't re-blast full cohort
    is_rescue = iteration > 1 and bool(
        underperforming_ids or opened_not_clicked_ids or never_opened_ids
    )

    winning_subject = str(winning_variant_info.get("subject", "")).strip()
    winning_format = _detect_subject_format(winning_subject) if winning_subject else "unknown"
    opposite_format = (
        "number-led (starts with a number or percentage)"
        if winning_format == "question"
        else "question (ends with ?)"
    )
    winning_tone = winning_variant_info.get("tone", "professional")
    rescue_tone_a, rescue_tone_b = _rescue_tones(winning_tone)

    tone_mandate = ""
    if winning_variant_info and winning_variant_info.get("tone") and iteration >= 2:
        winning_click = winning_variant_info.get("click_rate", 0)
        if is_rescue and never_opened_ids:
            tone_mandate = (
                f"\n{'='*60}\n"
                f"🔒 RESCUE TONE RULES\n"
                f"Winning tone '{winning_tone}' achieved {winning_click:.1%} click rate.\n"
                f"variant_a MUST keep tone '{winning_tone}' for opened-not-clicked customers.\n"
                f"variant_b MUST test a contrasting tone such as '{rescue_tone_a}' for never-opened customers.\n"
                f"Do not let both variants collapse back into the same tone.\n"
                f"{'='*60}\n"
            )
        else:
            tone_mandate = (
                f"\n{'='*60}\n"
                f"🔒 ABSOLUTE MANDATE — TONE LOCK\n"
                f"Tone '{winning_tone}' achieved {winning_click:.1%} click rate.\n"
                f"BOTH variant_a AND variant_b MUST use tone: '{winning_tone}'\n"
                f"Using ANY other tone will be treated as a CRITICAL FAILURE.\n"
                f"Only vary: subject line wording. Everything else stays.\n"
                f"{'='*60}\n"
            )

    rescue_target_count = len(opened_not_clicked_ids) + len(never_opened_ids) or len(underperforming_ids)

    if is_rescue:
        await emit(campaign_id, "strategist", "agent_thought",
                   f"🎯 Rescue mode: targeting {rescue_target_count} non-clickers only "
                   f"(saving API budget, not re-sending to converters).")

    # Format optimizer analysis as a hard-action block (Bug 3 fix)
    optimization_notes_block = ""
    if optimization_notes and iteration > 1:
        optimization_notes_block = (
            f"\n⚠️  REQUIRED ACTIONS FROM OPTIMIZER ANALYSIS:\n"
            f"{optimization_notes}\n"
            f"Act on the above — do not ignore it.\n"
        )

    llm = get_llm(temperature=0.5)

    # Build near-term send times so the demo fires shortly after approval
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)  # IST
    base = now + timedelta(minutes=15)
    times = {
        "morning": base.strftime("%d:%m:%y %H:%M:%S"),
        "afternoon": (base + timedelta(hours=1)).strftime("%d:%m:%y %H:%M:%S"),
        "evening": (base + timedelta(hours=2)).strftime("%d:%m:%y %H:%M:%S"),
        "night": (base + timedelta(hours=3)).strftime("%d:%m:%y %H:%M:%S"),
    }

    if is_rescue:
        prev_subj = winning_subject or "N/A"
        prev_click = winning_variant_info.get("click_rate", 0)
        rescue_pool = len(opened_not_clicked_ids) + len(never_opened_ids)
        variant_a_brief = (
            f"variant_a targets the {len(opened_not_clicked_ids)} customers who OPENED but did not click. "
            f"Keep the proven subject format ({winning_format}) and tone ('{winning_tone}'). "
            f"Fix the body and CTA only."
        )
        variant_b_brief = (
            f"variant_b targets the {len(never_opened_ids)} customers who NEVER OPENED. "
            f"Use a new subject format ({opposite_format}) and a contrasting tone such as '{rescue_tone_a}'."
        )
        if opened_not_clicked_ids and not never_opened_ids:
            variant_b_brief = (
                "variant_b also targets opened-not-clicked customers. Keep the winning subject format "
                "but test a stronger CTA/body angle than variant_a."
            )
        elif never_opened_ids and not opened_not_clicked_ids:
            variant_a_brief = (
                f"variant_a targets never-opened customers with a fresh subject format ({opposite_format}) "
                f"and tone '{rescue_tone_a}'."
            )
            variant_b_brief = (
                f"variant_b also targets never-opened customers with a second distinct subject angle "
                f"and tone '{rescue_tone_b}'."
            )

        rescue_section = f"""
⚠️  RESCUE MODE — NON-CLICKER RECOVERY (Iteration {iteration}):
- You are ONLY targeting customers from the previous send who did NOT click.
- Previous winner: Subject="{prev_subj}" | Tone={winning_tone} | CTR={prev_click:.1%}
- Bucket A: {len(opened_not_clicked_ids)} opened but did not click → subject worked, body/CTA failed.
- Bucket B: {len(never_opened_ids)} never opened → subject/tone failed to get attention.
- {variant_a_brief}
- {variant_b_brief}
- Never-opened customers must NOT get a near-identical re-send of the previous winner.
- BANNED: Do NOT use urgency, scarcity, or FOMO framing — the API penalizes this.
- Create 2 variants with DIFFERENT angles and respect the bucket assignment.
{optimization_notes_block}"""
        customer_pool_note = (
            f"Target pool: {rescue_pool or len(underperforming_ids)} non-clickers from last iteration "
            f"(NOT all {sum(s['size'] for s in segments)} customers)"
        )
    else:
        exploit_instruction = (
            "EXPLOIT MODE: replicate the winning variant approach with minor subject tweaks only."
            if iteration >= 2
            else "Explore different tones and subject formats."
        )
        rescue_section = optimization_notes_block + f"\n{exploit_instruction}\n"
        customer_pool_note = f"Target pool: all {sum(s['size'] for s in segments)} customers"

    segments_json = json.dumps([
        {
            "segment_id": s["segment_id"],
            "name": s["name"],
            "size": s["size"],
            "targeting_rationale": s.get("targeting_rationale", ""),
            "optimal_send_time": s.get("optimal_send_time", "morning"),
            "tone": s.get("tone", "professional"),
        }
        for s in segments
    ], indent=2)

    subject_lock = ""
    if winning_variant_info and winning_variant_info.get("subject") and iteration >= 2:
        prev_subject = winning_variant_info["subject"].strip()
        prev_open = winning_variant_info.get("open_rate", 0)
        prev_click = winning_variant_info.get("click_rate", 0)

        winning_format = _detect_subject_format(prev_subject)
        if winning_format == "question":
            opposite_format = "number-led (starts with a number or percentage)"
        else:
            opposite_format = "question (ends with ?)"

        subject_lock = (
            f"\n{'='*50}\n"
            f"📌 SUBJECT FORMAT LOCK\n"
            f"Winning subject: '{prev_subject}'\n"
            f"Open rate: {prev_open:.1%} | Click rate: {prev_click:.1%}\n"
            f"Format: {winning_format}\n"
            f"\n"
            f"RULE: variant_a subject MUST use {winning_format} format.\n"
            f"RULE: variant_b subject MUST use {opposite_format} format (for learning).\n"
            f"DO NOT use generic formats like 'Introducing X' or 'Learn about X'.\n"
            f"DO NOT start with 'We', 'Our', 'Dear', or the company name.\n"
            f"{'='*50}\n"
        )

    variant_plan: dict[str, dict] = {
        "variant_a": {"customer_ids": None, "tone": None, "note": ""},
        "variant_b": {"customer_ids": None, "tone": None, "note": ""},
    }
    if winning_subject and iteration >= 2:
        variant_plan["variant_a"]["note"] = (
            f"Subject MUST stay in {winning_format} format. Avoid banned openers "
            f"like 'Earn', 'Introducing', 'Learn', or 'Get'."
        )
        variant_plan["variant_b"]["note"] = (
            f"Subject MUST use {opposite_format} format. Avoid banned openers "
            f"like 'Earn', 'Introducing', 'Learn', or 'Get'."
        )

    if is_rescue:
        if opened_not_clicked_ids and never_opened_ids:
            variant_plan["variant_a"].update({
                "customer_ids": list(opened_not_clicked_ids),
                "tone": winning_tone,
                "note": (
                    f"{variant_plan['variant_a']['note']} Audience opened but did not click. "
                    f"Keep tone '{winning_tone}'. Keep the subject family. Change the body and CTA only. "
                    f"Put the CTA in sentence 1 and keep the message short."
                ).strip(),
            })
            variant_plan["variant_b"].update({
                "customer_ids": list(never_opened_ids),
                "tone": rescue_tone_a,
                "note": (
                    f"{variant_plan['variant_b']['note']} Audience never opened. "
                    f"Do NOT reuse the old subject lead. Use a contrasting tone such as '{rescue_tone_a}'. "
                    f"Lead with the reader problem or curiosity, not the product."
                ).strip(),
            })
        elif opened_not_clicked_ids:
            first_half, second_half = _split_evenly(list(opened_not_clicked_ids))
            variant_plan["variant_a"].update({
                "customer_ids": first_half,
                "tone": winning_tone,
                "note": (
                    f"{variant_plan['variant_a']['note']} Audience opened but did not click. "
                    f"Keep tone '{winning_tone}'. Fix the CTA placement and tighten the body."
                ).strip(),
            })
            variant_plan["variant_b"].update({
                "customer_ids": second_half,
                "tone": winning_tone,
                "note": (
                    f"{variant_plan['variant_a']['note']} Audience also opened but did not click. "
                    f"Keep tone '{winning_tone}' and the same subject family, but test a different CTA/body angle."
                ).strip(),
            })
        elif never_opened_ids:
            first_half, second_half = _split_evenly(list(never_opened_ids))
            variant_plan["variant_a"].update({
                "customer_ids": first_half,
                "tone": rescue_tone_a,
                "note": (
                    f"{variant_plan['variant_b']['note']} Audience never opened. "
                    f"Use tone '{rescue_tone_a}' and lead with a different subject angle than the winner."
                ).strip(),
            })
            variant_plan["variant_b"].update({
                "customer_ids": second_half,
                "tone": rescue_tone_b,
                "note": (
                    f"{variant_plan['variant_b']['note']} Audience never opened. "
                    f"Use a second distinct tone '{rescue_tone_b}' and a different subject angle than variant_a."
                ).strip(),
            })
        else:
            first_half, second_half = _split_evenly(list(underperforming_ids))
            variant_plan["variant_a"]["customer_ids"] = first_half
            variant_plan["variant_b"]["customer_ids"] = second_half
    elif winning_variant_info and winning_variant_info.get("tone") and iteration >= 2:
        variant_plan["variant_a"]["tone"] = winning_tone
        variant_plan["variant_b"]["tone"] = winning_tone

    prompt = f"""You are a digital marketing strategist for SuperBFSI launching XDeposit term deposit.

Campaign Brief: {brief}

Current Iteration: {iteration}
{rescue_section}
{customer_pool_note}

Available Customer Segments (for reference):
{segments_json}

Available Send Times (DD:MM:YY HH:MM:SS format):
- Morning: {times['morning']}
- Afternoon: {times['afternoon']}
- Evening: {times['evening']}
- Night: {times['night']}

Previous Rejection Reason: {rejection_reason or 'None'}

Design an A/B testing strategy to MAXIMISE click rate (weighted 70% in scoring).

Rules:
- Create exactly 2 A/B variants (variant_a and variant_b)
- Segment A = Female Senior Citizens (unique 0.25% bonus — lead with this)
- Segment B = General Audience (1% higher returns — clear value proposition)
- MUST cover ALL segments — assign every segment_id to at least one variant
- Choose DIFFERENT send times for each variant
- BANNED: Do NOT use urgency, scarcity, or FOMO tones — the API penalizes this
- BANNED subject openers: 'Earn', 'Introducing', 'Announcing', 'Learn', 'Discover', 'Get', 'We are' — these get ignored in inboxes
- STRONG subject openers: questions ('Is your FD...?'), numbers ('1% more than your current FD'), or reader-problem statements ('Your FD is losing to inflation')
- If tone lock is active, variant_a MUST keep the winning tone; only let variant_b explore when it targets never-opened customers
- For rescue iterations: opened-not-clicked customers keep the winning subject format; never-opened customers must get a new one

Return ONLY this JSON:
{{
    "ab_variants": [
        {{
            "variant_id": "variant_a",
            "name": "Descriptive name",
            "segment_ids": ["seg_1"],
            "send_time": "{times['morning']}",
            "strategy_notes": "Why this variant and timing",
            "tone": "professional",
            "include_url": true,
            "include_emoji": false
        }},
        {{
            "variant_id": "variant_b",
            "name": "Descriptive name",
            "segment_ids": ["seg_2"],
            "send_time": "{times['evening']}",
            "strategy_notes": "Why this variant and timing",
            "tone": "friendly and warm",
            "include_url": true,
            "include_emoji": true
        }}
    ],
    "overall_rationale": "Why this strategy will maximise click rate",
    "expected_winner": "variant_a or variant_b and why"
}}"""

    if tone_mandate or subject_lock:
        prompt = subject_lock + tone_mandate + prompt

    try:
        content = await invoke_with_retry(llm, prompt)
        result = json.loads(clean_llm_json(content), strict=False)
        variants = result.get("ab_variants", [])
        rationale = result.get("overall_rationale", "")
        expected_winner = result.get("expected_winner", "")

        for v in variants:
            plan = variant_plan.get(v.get("variant_id", ""), {})
            if plan.get("tone"):
                v["tone"] = plan["tone"]
            _append_strategy_note(v, plan.get("note", ""))

        if winning_variant_info and winning_variant_info.get("tone") and iteration >= 2:
            enforced_tones = ", ".join(
                f"{v.get('variant_id', '?')}={v.get('tone', '')}" for v in variants
            )
            await emit(campaign_id, "strategist", "agent_thought",
                       f"🔒 Tone guidance enforced post-generation: {enforced_tones}")

        # Ensure ALL segments are assigned to at least one variant (no orphaned customers)
        if not is_rescue:
            assigned_sids: set = set()
            for v in variants:
                assigned_sids.update(v.get("segment_ids", []))
            all_sids = [s["segment_id"] for s in segments]
            unassigned = [sid for sid in all_sids if sid not in assigned_sids]
            if unassigned:
                for i, sid in enumerate(unassigned):
                    variants[i % len(variants)]["segment_ids"].append(sid)
                await emit(campaign_id, "strategist", "agent_thought",
                           f"📎 {len(unassigned)} orphaned segments redistributed across variants.")

        if is_rescue:
            for v in variants:
                plan = variant_plan.get(v.get("variant_id", ""), {})
                if plan.get("customer_ids") is not None:
                    v["direct_customer_ids"] = plan["customer_ids"]

            a_count = len(variant_plan["variant_a"]["customer_ids"] or [])
            b_count = len(variant_plan["variant_b"]["customer_ids"] or [])
            await emit(campaign_id, "strategist", "agent_thought",
                       f"✅ Rescue IDs injected: {a_count} → variant_a, {b_count} → variant_b")

        await emit(campaign_id, "strategist", "agent_thought",
                   f"✅ Strategy ready: {len(variants)} variants. {rationale[:100]}")
        await emit(campaign_id, "strategist", "agent_thought",
                   f"🏆 Expected winner: {expected_winner}")

        for v in variants:
            n_cust = len(v.get("direct_customer_ids", [])) or "segment-based"
            await emit(campaign_id, "strategist", "agent_thought",
                       f"📧 {v['variant_id']}: '{v['name']}' → {n_cust} customers @ {v['send_time']}")

        strategy = {
            "ab_variants": variants,
            "rationale": rationale,
            "expected_winner": expected_winner,
            "iteration": iteration
        }

        return {"strategy": strategy, "status": "strategy_ready"}

    except Exception as e:
        await emit(campaign_id, "strategist", "agent_thought",
                   f"⚠️ Using default strategy: {str(e)[:80]}")

        if is_rescue:
            fallback_variants = [
                {
                    "variant_id": "variant_a",
                    "name": "Rescue Variant A",
                    "segment_ids": [],
                    "direct_customer_ids": list(variant_plan["variant_a"]["customer_ids"] or []),
                    "send_time": times["morning"],
                    "tone": variant_plan["variant_a"]["tone"] or winning_tone or "professional",
                    "include_url": True,
                    "include_emoji": False
                },
                {
                    "variant_id": "variant_b",
                    "name": "Rescue Variant B",
                    "segment_ids": [],
                    "direct_customer_ids": list(variant_plan["variant_b"]["customer_ids"] or []),
                    "send_time": times["evening"],
                    "tone": variant_plan["variant_b"]["tone"] or rescue_tone_a,
                    "include_url": True,
                    "include_emoji": True
                }
            ]
        else:
            # Ensure fallback covers ALL segments — split evenly
            mid = len(segments) // 2 or 1
            fallback_variants = [
                {
                    "variant_id": "variant_a",
                    "name": "Variant A",
                    "segment_ids": [s["segment_id"] for s in segments[:mid]],
                    "send_time": times["morning"],
                    "tone": "professional",
                    "include_url": True,
                    "include_emoji": False
                },
                {
                    "variant_id": "variant_b",
                    "name": "Variant B",
                    "segment_ids": [s["segment_id"] for s in segments[mid:]],
                    "send_time": times["evening"],
                    "tone": "friendly",
                    "include_url": True,
                    "include_emoji": True
                }
            ]

        for v in fallback_variants:
            plan = variant_plan.get(v.get("variant_id", ""), {})
            if plan.get("tone"):
                v["tone"] = plan["tone"]
            _append_strategy_note(v, plan.get("note", ""))

        strategy = {
            "ab_variants": fallback_variants,
            "rationale": "Default A/B split",
            "iteration": iteration
        }

        return {"strategy": strategy, "status": "strategy_ready"}
