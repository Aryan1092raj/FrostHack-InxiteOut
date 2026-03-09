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
        rescue_section = f"""
⚠️  RESCUE TARGETING MODE (Iteration {iteration}):
- You are ONLY targeting {len(underperforming_ids)} customers who did NOT click last time.
- DO NOT create a fresh split of all customers — that wastes API calls.
- The WINNING variant from last run achieved {winning_variant_info.get('click_rate', 0):.1%} CTR:
  * Subject: "{winning_variant_info.get('subject', 'N/A')}"
  * Tone: {winning_variant_info.get('tone', 'professional')}
- Create 2 variants that BUILD ON this winning approach with different subject line formats:
  * If previous was a statement → try a question: "Is your FD earning enough?"
  * If previous was generic → try number-led: "Earn 1% more — here's how XDeposit compares"
  * Try urgency: "Lock in XDeposit's best-ever rate before it ends"
- Both variants will only target subsets of the {len(underperforming_ids)} non-clickers.
"""
        customer_pool_note = (
            f"Target pool: {len(underperforming_ids)} non-clickers from last iteration "
            f"(NOT all {sum(s['size'] for s in segments)} customers)"
        )
    else:
        rescue_section = ""
        customer_pool_note = f"Target pool: all {sum(s['size'] for s in segments)} customers"

    prompt = f"""You are a digital marketing strategist for SuperBFSI launching XDeposit term deposit.

Campaign Brief: {brief}

Current Iteration: {iteration}
{rescue_section}
{customer_pool_note}

Available Customer Segments (for reference):
{json.dumps([{{
    "segment_id": s["segment_id"],
    "name": s["name"],
    "size": s["size"],
    "targeting_rationale": s.get("targeting_rationale", ""),
    "optimal_send_time": s.get("optimal_send_time", "morning"),
    "tone": s.get("tone", "professional")
}} for s in segments], indent=2)}

Available Send Times (DD:MM:YY HH:MM:SS format):
- Morning: {times['morning']}
- Afternoon: {times['afternoon']}
- Evening: {times['evening']}
- Night: {times['night']}

Previous Rejection Reason: {rejection_reason or 'None'}
Optimization Notes: {optimization_notes or 'First run — no previous data'}

Design an A/B testing strategy to MAXIMISE click rate (weighted 70% in scoring).

Rules:
- Create exactly 2 A/B variants (variant_a and variant_b)
- Choose DIFFERENT send times for each variant
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
            fallback_variants = [
                {
                    "variant_id": "variant_a",
                    "name": "Variant A",
                    "segment_ids": [s["segment_id"] for s in segments[:len(segments)//2]],
                    "send_time": times["morning"],
                    "tone": "professional",
                    "include_url": True,
                    "include_emoji": False
                },
                {
                    "variant_id": "variant_b",
                    "name": "Variant B",
                    "segment_ids": [s["segment_id"] for s in segments[len(segments)//2:]],
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
    campaign_id = state["campaign_id"]
    brief = state["brief"]
    segments = state["segments"]
    iteration = state.get("iteration", 1)
    optimization_notes = state.get("optimization_notes", "")
    rejection_reason = state.get("rejection_reason", "")

    await emit(campaign_id, "strategist", "agent_thought",
               f"Planning campaign strategy (iteration {iteration})...")

    if rejection_reason:
        await emit(campaign_id, "strategist", "agent_thought",
                   f"Incorporating rejection feedback: {rejection_reason}")

    if optimization_notes:
        await emit(campaign_id, "strategist", "agent_thought",
                   f"Applying optimization insights: {optimization_notes}")

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

    prompt = f"""You are a digital marketing strategist for SuperBFSI launching XDeposit term deposit.

Campaign Brief: {brief}

Current Iteration: {iteration}
Available Customer Segments:
{json.dumps([{
    "segment_id": s["segment_id"],
    "name": s["name"],
    "size": s["size"],
    "targeting_rationale": s.get("targeting_rationale", ""),
    "optimal_send_time": s.get("optimal_send_time", "morning"),
    "tone": s.get("tone", "professional")
} for s in segments], indent=2)}

Available Send Times (use DD:MM:YY HH:MM:SS format):
- Morning: {times['morning']}
- Afternoon: {times['afternoon']}
- Evening: {times['evening']}
- Night: {times['night']}

Previous Rejection Reason: {rejection_reason or 'None'}
Optimization Notes from Last Run: {optimization_notes or 'First run — no previous data'}

Design an A/B testing strategy to maximize open rate and click rate.
Note: Click rate is weighted 70%, open rate 30% in scoring.

Rules:
- Create exactly 2 A/B variants (variant_a and variant_b)
- Assign each segment to one variant
- Choose different send times for each variant to test timing
- Each variant targets different but complementary segments

Return ONLY this JSON:
{{
    "ab_variants": [
        {{
            "variant_id": "variant_a",
            "name": "Professional Tone — Morning",
            "segment_ids": ["seg_1", "seg_2"],
            "send_time": "{times['morning']}",
            "strategy_notes": "Why this variant and timing",
            "tone": "professional",
            "include_url": true,
            "include_emoji": false
        }},
        {{
            "variant_id": "variant_b",
            "name": "Friendly Tone — Evening",
            "segment_ids": ["seg_3"],
            "send_time": "{times['evening']}",
            "strategy_notes": "Why this variant and timing",
            "tone": "friendly and warm",
            "include_url": true,
            "include_emoji": true
        }}
    ],
    "overall_rationale": "Why this A/B strategy will maximize click rate",
    "expected_winner": "variant_a or variant_b and why"
}}"""

    try:
        content = await invoke_with_retry(llm, prompt)
        result = json.loads(clean_llm_json(content), strict=False)
        variants = result.get("ab_variants", [])
        rationale = result.get("overall_rationale", "")
        expected_winner = result.get("expected_winner", "")

        await emit(campaign_id, "strategist", "agent_thought",
                   f"✅ Strategy ready: {len(variants)} A/B variants planned.")
        await emit(campaign_id, "strategist", "agent_thought",
                   f"📋 Rationale: {rationale}")
        await emit(campaign_id, "strategist", "agent_thought",
                   f"🏆 Expected winner: {expected_winner}")

        for v in variants:
            await emit(campaign_id, "strategist", "agent_thought",
                       f"📧 {v['variant_id']}: '{v['name']}' → send at {v['send_time']}")

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

        strategy = {
            "ab_variants": [
                {
                    "variant_id": "variant_a",
                    "name": "Variant A",
                    "segment_ids": [s["segment_id"] for s in segments[:len(segments)//2]],
                    "send_time": times["morning"],
                    "tone": "professional",
                    "include_url": True,
                    "include_emoji": False
                },
                {
                    "variant_id": "variant_b",
                    "name": "Variant B",
                    "segment_ids": [s["segment_id"] for s in segments[len(segments)//2:]],
                    "send_time": times["evening"],
                    "tone": "friendly",
                    "include_url": True,
                    "include_emoji": True
                }
            ],
            "rationale": "Default A/B split",
            "iteration": iteration
        }

        return {"strategy": strategy, "status": "strategy_ready"}
