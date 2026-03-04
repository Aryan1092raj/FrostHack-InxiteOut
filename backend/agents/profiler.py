import json
import itertools
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json
from db.database import get_cached_cohort, save_cohort_cache
from tools.campaignx_tools import tool_get_customer_cohort


async def profiler_node(state: CampaignState) -> dict:
    campaign_id = state["campaign_id"]
    brief = state["brief"]

    await emit(campaign_id, "profiler", "agent_thought",
               "Starting customer profiling...")

    # Use cache first — saves rate limit
    customers = get_cached_cohort()

    if not customers:
        await emit(campaign_id, "profiler", "action",
                   "No cache found. Fetching customer cohort from CampaignX API...")
        result = tool_get_customer_cohort("Need full cohort for segmentation")
        if "error" in result:
            await emit(campaign_id, "profiler", "error",
                       f"API error: {result['error']}")
            customers = []
        else:
            customers = result.get("data", [])
            save_cohort_cache(customers)
            await emit(campaign_id, "profiler", "action",
                       f"✅ Fetched {len(customers)} customers. Saved to cache.")
    else:
        await emit(campaign_id, "profiler", "action",
                   f"✅ Loaded {len(customers)} customers from cache.")

    # LLM builds intelligent segments
    await emit(campaign_id, "profiler", "agent_thought",
               "Analyzing demographics to build targeted segments...")

    llm = get_llm(temperature=0.3)
    sample = list(itertools.islice(customers, 60)) if len(customers) > 60 else customers

    prompt = f"""You are a customer analytics expert for SuperBFSI, an Indian BFSI company launching XDeposit term deposit product.

Campaign Brief: {brief}

Customer Data ({len(sample)} sample of {len(customers)} total):
{json.dumps(sample, indent=2)}

Create 3-5 meaningful demographic segments from this data optimized for the XDeposit email campaign.

Key rules from the brief:
- Female senior citizens get an EXTRA 0.25% return — they need a dedicated segment
- Do NOT skip inactive customers
- Optimize for open rate and click rate

Return ONLY this JSON structure (no other text):
{{
    "segments": [
        {{
            "segment_id": "seg_1",
            "name": "Female Senior Citizens",
            "description": "Women aged 55+ — eligible for special 0.25% bonus",
            "customer_ids": ["CUST001", "CUST002"],
            "size": 2,
            "targeting_rationale": "Special rate applies — high conversion potential",
            "optimal_send_time": "morning",
            "tone": "warm and personal"
        }}
    ],
    "total_customers": {len(customers)},
    "insights": "Brief insight about the overall customer base"
}}

Use ONLY real customer_ids from the data above. Cover ALL {len(customers)} customers across segments (no customer left out)."""

    try:
        response = llm.invoke(prompt)
        result = json.loads(clean_llm_json(response.content))
        segments = result.get("segments", [])
        insights = result.get("insights", "")

        await emit(campaign_id, "profiler", "agent_thought",
                   f"✅ Built {len(segments)} segments. Insight: {insights}")

        for seg in segments:
            await emit(campaign_id, "profiler", "agent_thought",
                       f"📊 Segment '{seg['name']}': {seg['size']} customers — {seg['targeting_rationale']}")

        return {
            "customers": customers,
            "segments": segments,
            "status": "profiled"
        }

    except Exception as e:
        await emit(campaign_id, "profiler", "error",
                   f"LLM error: {str(e)}. Using fallback segmentation.")

        # Fallback — simple split
        mid = len(customers) // 2
        segments = [
            {
                "segment_id": "seg_1",
                "name": "Segment A",
                "description": "First half of customers",
                "customer_ids": [c["customer_id"] for c in itertools.islice(customers, mid)],
                "size": mid,
                "targeting_rationale": "A/B test group A",
                "optimal_send_time": "morning",
                "tone": "professional"
            },
            {
                "segment_id": "seg_2",
                "name": "Segment B",
                "description": "Second half of customers",
                "customer_ids": [c["customer_id"] for c in itertools.islice(customers, mid, None)],
                "size": len(customers) - mid,
                "targeting_rationale": "A/B test group B",
                "optimal_send_time": "evening",
                "tone": "friendly"
            }
        ]

        return {"customers": customers, "segments": segments, "status": "profiled"}
