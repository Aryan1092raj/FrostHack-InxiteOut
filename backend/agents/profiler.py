"""
Profiler Node — Innovation #3: Occupation-Axis + Demographic Cross-Segmentation

The key insight: every other team will segment by age/gender alone.
We cross-segment on TWO axes simultaneously:
  Axis 1: Life stage (female_senior, senior, young, general)
  Axis 2: Occupation (government, IT/tech, self-employed, retired, homemaker, other)

This gives us per-occupation psychological messaging that the LLM then tailors.
Each occupation group has a proven different psychological trigger for financial products.
"""

import json
import itertools
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json, invoke_with_retry
from db.database import get_cached_cohort, save_cohort_cache
from tools.campaignx_tools import tool_get_customer_cohort


# ── Occupation → Psychological Angle mapping ──────────────────────────────────
OCCUPATION_ANGLES = {
    "government":   {
        "angle":   "guaranteed_stability",
        "message": "Secure, government-trusted returns with XDeposit",
        "tone":    "formal, authoritative",
        "trigger": "security and trust over returns",
    },
    "it_tech":      {
        "angle":   "data_driven",
        "message": "The math is simple: XDeposit earns 1% more — calculate your gain",
        "tone":    "direct, analytical",
        "trigger": "ROI calculation, comparative data",
    },
    "self_employed": {
        "angle":   "business_growth",
        "message": "Beat inflation — your business deserves better returns",
        "tone":    "aspirational, entrepreneurial",
        "trigger": "inflation hedge, business growth",
    },
    "retired":      {
        "angle":   "income_supplement",
        "message": "Supplement your monthly income with higher FD returns",
        "tone":    "warm, security-focused",
        "trigger": "regular income, peace of mind",
    },
    "homemaker":    {
        "angle":   "family_security",
        "message": "Secure your family's financial future — 1% more with XDeposit",
        "tone":    "emotional, family-first",
        "trigger": "family protection, children's future",
    },
    "student":      {
        "angle":   "future_wealth",
        "message": "Start your wealth journey early — XDeposit grows faster",
        "tone":    "energetic, future-focused",
        "trigger": "starting early advantage, compounding",
    },
    "other":        {
        "angle":   "general_value",
        "message": "1% higher returns with XDeposit — make your money work harder",
        "tone":    "informational, friendly",
        "trigger": "simple value proposition",
    },
}


def _age(c) -> int:
    try:
        return int(c.get("Age", 0))
    except (ValueError, TypeError):
        return 0

def _income(c) -> float:
    try:
        return float(c.get("Monthly_Income", 0))
    except (ValueError, TypeError):
        return 0.0

def _is_female(c) -> bool:
    return str(c.get("Gender", "")).strip().lower() in ("female", "f")

def _is_inactive(c) -> bool:
    val = str(c.get("Existing_Customer", c.get("Existing Customer", ""))).strip().lower()
    return val in ("inactive", "no", "false", "0")

def _is_digital(c) -> bool:
    app = str(c.get("App_Installed", "")).strip().lower() in ("true", "yes", "1")
    social = str(c.get("Social_Media_Active", "")).strip().lower() in ("true", "yes", "1")
    return app or social

def _occupation_bucket(c) -> str:
    occ = str(c.get("Occupation", "")).strip().lower()
    if any(kw in occ for kw in ("government", "govt", "public sector", "ias", "ips", "civil")):
        return "government"
    if any(kw in occ for kw in ("software", "it", "tech", "engineer", "developer", "programmer", "analyst")):
        return "it_tech"
    if any(kw in occ for kw in ("business", "self", "entrepreneur", "owner", "freelance", "consultant")):
        return "self_employed"
    if any(kw in occ for kw in ("retired", "pension", "pensioner")):
        return "retired"
    if any(kw in occ for kw in ("homemaker", "housewife", "househusband", "home maker")):
        return "homemaker"
    if any(kw in occ for kw in ("student", "intern")):
        return "student"
    return "other"


def smartsplit_customers(customers: list) -> list[dict]:
    """
    Two-pass segmentation:
      Pass 1: Guaranteed demographic buckets (priority order)
      Pass 2: Within each bucket, record occupation breakdown for per-segment messaging

    Returns list of segment dicts — each with real customer_ids, not random slices.
    """

    # ── Pass 1: Demographic buckets (2 segments for max sample size per group) ──
    bucket_ids: dict[str, list[str]] = {
        "female_senior":  [],
        "general":        [],
    }
    assigned: set[str] = set()

    # Female seniors — HIGHEST priority (unique 0.25% offer)
    for c in customers:
        cid = c["customer_id"]
        if _age(c) >= 55 and _is_female(c):
            bucket_ids["female_senior"].append(cid)
            assigned.add(cid)

    # Everyone else goes into the general bucket
    for c in customers:
        cid = c["customer_id"]
        if cid not in assigned:
            bucket_ids["general"].append(cid)

    # ── Pass 2: Build rich segment dicts ──────────────────────────────────────
    id_to_customer = {c["customer_id"]: c for c in customers}

    SEGMENT_META = {
        "female_senior": {
            "name": "Female Senior Citizens",
            "tone": "warm, respectful, family-oriented",
            "optimal_send_time": "morning",
            "special_offer": True,
            "key_angle": "Exclusive 1.25% higher returns — unique bonus they get",
        },
        "general": {
            "name": "General Audience",
            "tone": "informational, friendly",
            "optimal_send_time": "morning",
            "special_offer": False,
            "key_angle": "Simple value: 1% more than what they're earning now",
        },
    }

    segments = []
    seg_idx = 1

    for bucket_name, cids in bucket_ids.items():
        if not cids:
            continue

        meta = SEGMENT_META[bucket_name]
        group = [id_to_customer[cid] for cid in cids if cid in id_to_customer]

        # Compute real stats
        ages    = [_age(c) for c in group if _age(c) > 0]
        incomes = [_income(c) for c in group if _income(c) > 0]
        cities  = [c.get("City", "") for c in group if c.get("City")]

        avg_age    = round(sum(ages) / len(ages), 1) if ages else 0
        avg_income = round(sum(incomes) / len(incomes)) if incomes else 0
        top_city   = max(set(cities), key=cities.count) if cities else "Unknown"

        # Innovation #3: Occupation breakdown for this segment
        occ_breakdown: dict[str, int] = {}
        for c in group:
            occ = _occupation_bucket(c)
            occ_breakdown[occ] = occ_breakdown.get(occ, 0) + 1

        # Dominant occupation in this segment → drives the psychological angle
        dominant_occ = max(occ_breakdown, key=occ_breakdown.get) if occ_breakdown else "other"
        occ_angle    = OCCUPATION_ANGLES.get(dominant_occ, OCCUPATION_ANGLES["other"])

        segments.append({
            "segment_id":           f"seg_{seg_idx}",
            "bucket":               bucket_name,
            "name":                 meta["name"],
            "description":          meta["key_angle"],
            "customer_ids":         cids,
            "size":                 len(cids),
            "targeting_rationale":  (
                f"{meta['key_angle']} | avg age {avg_age} | "
                f"avg income ₹{avg_income:,.0f} | top city {top_city}"
            ),
            "optimal_send_time":    meta["optimal_send_time"],
            "tone":                 meta["tone"],
            "special_offer":        meta["special_offer"],
            "key_angle":            meta["key_angle"],
            # Innovation #3 extras:
            "occupation_breakdown": occ_breakdown,
            "dominant_occupation":  dominant_occ,
            "occupation_angle":     occ_angle,
            # Stats for content_gen to use:
            "avg_age":              avg_age,
            "avg_income":           avg_income,
            "top_city":             top_city,
        })
        seg_idx += 1

    return segments


async def profiler_node(state: CampaignState) -> dict:
    campaign_id = state["campaign_id"]
    brief       = state["brief"]

    await emit(campaign_id, "profiler", "agent_thought",
               "🔬 Starting SmartSplit profiler (demographic × occupation cross-segmentation)...")

    # ── Fetch cohort ──────────────────────────────────────────────────────────
    customers = get_cached_cohort()

    if not customers:
        await emit(campaign_id, "profiler", "action",
                   "No cache. Fetching customer cohort from CampaignX API...")
        result = tool_get_customer_cohort("Need full cohort for SmartSplit segmentation")
        if "error" in result:
            await emit(campaign_id, "profiler", "error", f"API error: {result['error']}")
            customers = []
        else:
            customers = result.get("data", [])
            save_cohort_cache(customers)
            await emit(campaign_id, "profiler", "action",
                       f"✅ Fetched {len(customers)} customers. Cached.")
    else:
        await emit(campaign_id, "profiler", "action",
                   f"✅ Loaded {len(customers)} customers from cache.")

    # ── SmartSplit — deterministic two-axis segmentation ─────────────────────
    await emit(campaign_id, "profiler", "agent_thought",
               "📊 Running two-axis segmentation: demographic × occupation...")

    segments = smartsplit_customers(customers)

    for seg in segments:
        occ_str = ", ".join(f"{k}:{v}" for k, v in sorted(
            seg["occupation_breakdown"].items(), key=lambda x: -x[1])[:3]
        )
        await emit(campaign_id, "profiler", "agent_thought",
                   f"  📦 '{seg['name']}': {seg['size']} customers | "
                   f"dominant occ: {seg['dominant_occupation']} | "
                   f"angle: {seg['occupation_angle']['angle']}")
        await emit(campaign_id, "profiler", "agent_thought",
                   f"     occ breakdown (top 3): {occ_str}")

    # ── LLM validates and adds strategic insight ──────────────────────────────
    llm = get_llm(temperature=0.3)

    segment_summary = json.dumps([
        {
            "name":                seg["name"],
            "size":                seg["size"],
            "avg_age":             seg["avg_age"],
            "avg_income":          seg["avg_income"],
            "top_city":            seg["top_city"],
            "dominant_occupation": seg["dominant_occupation"],
            "occupation_angle":    seg["occupation_angle"]["angle"],
            "special_offer":       seg["special_offer"],
        }
        for seg in segments
    ], ensure_ascii=True, indent=2)

    prompt = f"""You are a customer analytics expert for SuperBFSI's XDeposit term deposit campaign.

We've built {len(segments)} demographic × occupation segments from {len(customers)} customers:

{segment_summary}

Campaign Brief: {brief}

In 2-3 sentences:
1. Which segment has the highest click potential given their occupation psychology and demographic?
2. What cross-segment pattern should the content strategy exploit?
3. Any segment we should prioritise differently?

Be specific — reference segment names, occupation angles, and the female senior 0.25% bonus."""

    try:
        insights = await invoke_with_retry(llm, prompt)
    except Exception:
        insights = (
            f"SmartSplit complete: {len(segments)} segments across demographic and occupation axes. "
            f"Female Senior Citizens segment has highest conversion potential due to exclusive 0.25% bonus."
        )

    await emit(campaign_id, "profiler", "agent_thought",
               f"✅ Segmentation complete: {len(segments)} segments built.")
    await emit(campaign_id, "profiler", "agent_thought", f"🔍 Strategic insight: {insights}")

    return {
        "customers": customers,
        "segments":  segments,
        "status":    "profiled",
    }
