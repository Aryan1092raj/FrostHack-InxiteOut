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

    await emit(campaign_id, "strategist", "agent_thought",
               f"Planning campaign strategy (iteration {iteration})...")

    if rejection_reason:
        await emit(campaign_id, "strategist", "agent_thought",
                   f"Incorporating rejection feedback: {rejection_reason}")

    if optimization_notes:
        await emit(campaign_id, "strategist", "agent_thought",
                   f"Applying optimization insights: {optimization_notes}")

    llm = get_llm(temperature=0.5)

    # Build future send times
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)  # IST
    times = {
        "morning": (now + timedelta(hours=1)).strftime("%d:%m:%y 09:00:00"),
        "afternoon": (now + timedelta(hours=2)).strftime("%d:%m:%y 13:00:00"),
        "evening": (now + timedelta(hours=3)).strftime("%d:%m:%y 18:00:00"),
        "night": (now + timedelta(hours=4)).strftime("%d:%m:%y 20:00:00"),
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
