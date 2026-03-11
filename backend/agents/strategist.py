import json
from datetime import datetime, timedelta
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json, invoke_with_retry


async def strategist_node(state: CampaignState) -> dict:
    campaign_id = state["campaign_id"]
    brief = state["brief"]
    segments = state["segments"]
    iteration = state.get("iteration", 1)
    optimization_notes = state.get("optimization_notes", "")
    rejection_reason = state.get("rejection_reason", "")
    underperforming_ids: list = state.get("underperforming_customer_ids", [])
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
    is_rescue = iteration > 1 and len(underperforming_ids) > 0

    if is_rescue:
        await emit(campaign_id, "strategist", "agent_thought",
                   f"🎯 Rescue mode: targeting {len(underperforming_ids)} non-clickers only "
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

    # Build future send times — always use tomorrow to guarantee future
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)  # IST
    tomorrow = now + timedelta(days=1)
    times = {
        "morning": tomorrow.strftime("%d:%m:%y 09:00:00"),
        "afternoon": tomorrow.strftime("%d:%m:%y 13:00:00"),
        "evening": tomorrow.strftime("%d:%m:%y 18:00:00"),
        "night": tomorrow.strftime("%d:%m:%y 20:00:00"),
    }

    if is_rescue:
        # Non-clickers already saw+ignored the previous approach — ALWAYS explore a different angle.
        # EXPLOIT (replicate winner) is counterproductive for people who already rejected it.
        prev_tone   = winning_variant_info.get('tone', 'professional')
        prev_subj   = winning_variant_info.get('subject', 'N/A')
        prev_click  = winning_variant_info.get('click_rate', 0)

        # Determine the opposite tone to try
        explore_tone_hint = (
            "aspirational or warm/personal"
            if "professional" in prev_tone or "analytical" in prev_tone
            else "analytical/number-led or trust-building"
        )

        rescue_section = f"""
⚠️  EXPLORE MODE — NON-CLICKER RESCUE (Iteration {iteration}):
- You are ONLY targeting {len(underperforming_ids)} customers who saw the previous email and DID NOT click.
- They already ignored: Subject="{prev_subj}" | Tone={prev_tone} | CTR={prev_click:.1%}
- DO NOT replicate the previous approach — they rejected it. A near-identical re-send will continue to decline.
- MANDATE: Use a COMPLETELY DIFFERENT angle and tone from what ran before.
  * Previous tone was "{prev_tone}" → try {explore_tone_hint} instead
  * If previous led with rate/numbers → try leading with a relatable problem ("Your FD could be doing more")
  * If previous led with a statement → try a question or narrative opening
  * Change the emotional hook: try trust/security vs. returns-math vs. social proof
- BANNED: Do NOT use urgency, scarcity, or FOMO framing — the API penalizes this.
- Create 2 variants with DIFFERENT angles — do NOT make them variations of each other.
- Both variants target only the {len(underperforming_ids)} non-clickers (split evenly).
{optimization_notes_block}"""
        customer_pool_note = (
            f"Target pool: {len(underperforming_ids)} non-clickers from last iteration "
            f"(NOT all {sum(s['size'] for s in segments)} customers)"
        )
    else:
        exploit_instruction = (
            "EXPLOIT MODE: replicate the winning variant approach with minor subject tweaks only."
            if iteration >= 2
            else "Explore different tones and subject formats."
        )
        # Add hard tone constraint when a winning variant has an identified tone
        if winning_variant_info and winning_variant_info.get("tone"):
            winning_tone = winning_variant_info["tone"]
            exploit_instruction += (
                f"\n\nCRITICAL: The winning tone is '{winning_tone}' — BOTH variants MUST use this tone."
                f"\nDO NOT generate any variant with a different tone."
                f"\nOnly vary the subject line format between the two variants."
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
- Preferred tones: trust-building, aspirational, informational, warm/personal
- For rescue iterations: use DIFFERENT subject formats to what already ran

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

    try:
        content = await invoke_with_retry(llm, prompt)
        result = json.loads(clean_llm_json(content), strict=False)
        variants = result.get("ab_variants", [])
        rationale = result.get("overall_rationale", "")
        expected_winner = result.get("expected_winner", "")

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

        # For rescue iterations: override customer IDs with the real underperforming
        # pool split evenly across the two variants — content_gen uses these directly.
        if is_rescue and underperforming_ids:
            mid = len(underperforming_ids) // 2
            if len(variants) >= 2:
                variants[0]["direct_customer_ids"] = underperforming_ids[:mid]
                variants[1]["direct_customer_ids"] = underperforming_ids[mid:]
            elif len(variants) == 1:
                variants[0]["direct_customer_ids"] = underperforming_ids

            await emit(campaign_id, "strategist", "agent_thought",
                       f"✅ Rescue IDs injected: "
                       f"{mid} → variant_a, {len(underperforming_ids) - mid} → variant_b")

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

        if is_rescue and underperforming_ids:
            mid = len(underperforming_ids) // 2
            fallback_variants = [
                {
                    "variant_id": "variant_a",
                    "name": "Rescue Variant A",
                    "segment_ids": [],
                    "direct_customer_ids": underperforming_ids[:mid],
                    "send_time": times["morning"],
                    "tone": "professional",
                    "include_url": True,
                    "include_emoji": False
                },
                {
                    "variant_id": "variant_b",
                    "name": "Rescue Variant B",
                    "segment_ids": [],
                    "direct_customer_ids": underperforming_ids[mid:],
                    "send_time": times["evening"],
                    "tone": "friendly",
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

        strategy = {
            "ab_variants": fallback_variants,
            "rationale": "Default A/B split",
            "iteration": iteration
        }

        return {"strategy": strategy, "status": "strategy_ready"}
