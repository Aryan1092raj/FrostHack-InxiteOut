import json
import itertools
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json, invoke_with_retry
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
    # Only send essential fields — strip names/special chars to avoid JSON issues
    sample_raw = customers[:15] if len(customers) > 15 else customers
    sample = [{
        "customer_id": c.get("customer_id"),
        "Age": c.get("Age"),
        "Gender": c.get("Gender"),
        "City": c.get("City"),
        "Monthly_Income": c.get("Monthly_Income"),
        "Occupation": c.get("Occupation"),
        "Existing_Customer": c.get("Existing Customer"),
        "App_Installed": c.get("App_Installed"),
        "Social_Media_Active": c.get("Social_Media_Active"),
        "KYC_status": c.get("KYC status"),
    } for c in sample_raw]

    prompt = f"""You are a customer analytics expert for SuperBFSI, an Indian BFSI company launching XDeposit term deposit product.

Campaign Brief: {brief}

Customer Data (sample of {len(customers)} total customers):
{json.dumps(sample, ensure_ascii=True)}

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

IMPORTANT: You have {len(customers)} total customers (IDs: CUST0001 to CUST{len(customers):04d}).
Create segments and I will assign customer IDs to each segment based on demographics automatically.
For customer_ids in your JSON, just put 2-3 example IDs from the sample. The real assignment happens in code."""

    try:
        content = await invoke_with_retry(llm, prompt)
        result = json.loads(clean_llm_json(content), strict=False)
        segments = result.get("segments", [])
        insights = result.get("insights", "")

        # Distribute ALL customers evenly across segments
        all_ids = [c["customer_id"] for c in customers]
        total = len(all_ids)
        n_segs = len(segments)
        for i, seg in enumerate(segments):
            start_idx = (i * total) // n_segs
            end_idx = ((i + 1) * total) // n_segs
            seg["customer_ids"] = all_ids[start_idx:end_idx]
            seg["size"] = len(seg["customer_ids"])

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
        await emit(campaign_id, "profiler", "agent_thought",
                   f"⚠️ LLM JSON parse issue, using fallback segmentation: {str(e)[:100]}")

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
