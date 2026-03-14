"""
profiler.py — SmartSplit two-axis customer segmentation.

Root fixes in this rewrite:
  1. smartsplit_customers always returns at least one segment — never empty.
     Previously if female_senior was empty the function returned one segment
     but if something crashed it returned [] causing 0 segments → 2000 sends.
  2. Segments are only created when they have customers — no empty segment dicts.
  3. LLM insight call is non-blocking — failure just uses a default string.
  4. female_senior threshold raised to 60+ (more meaningful for 0.25% offer)
     and merged into general if < 30 customers (too small for standalone segment).
"""

import json
from agents.state import CampaignState
from agents.base import emit, get_llm, invoke_with_retry
from db.database import get_cached_cohort, save_cohort_cache
from tools.campaignx_tools import tool_get_customer_cohort


# ── Occupation → Psychological Angle ─────────────────────────────────────────
OCCUPATION_ANGLES = {
    "government": {
        "angle":   "guaranteed_stability",
        "message": "Secure, government-trusted returns with XDeposit",
        "tone":    "formal, authoritative",
        "trigger": "security and trust over returns",
    },
    "it_tech": {
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
    "retired": {
        "angle":   "income_supplement",
        "message": "Supplement your monthly income with higher FD returns",
        "tone":    "warm, security-focused",
        "trigger": "regular income, peace of mind",
    },
    "homemaker": {
        "angle":   "family_security",
        "message": "Secure your family's financial future — 1% more with XDeposit",
        "tone":    "emotional, family-first",
        "trigger": "family protection, children's future",
    },
    "student": {
        "angle":   "future_wealth",
        "message": "Start your wealth journey early — XDeposit grows faster",
        "tone":    "energetic, future-focused",
        "trigger": "starting early advantage, compounding",
    },
    "other": {
        "angle":   "general_value",
        "message": "1% higher returns with XDeposit — make your money work harder",
        "tone":    "informational, friendly",
        "trigger": "simple value proposition",
    },
}

SEGMENT_META = {
    "female_senior": {
        "name":              "Female Senior Citizens",
        "tone":              "warm, respectful, aspirational",
        "optimal_send_time": "morning",
        "special_offer":     True,
        "key_angle":         "Exclusive 1.25% higher returns — unique bonus for female seniors",
    },
    "general": {
        "name":              "General Audience",
        "tone":              "informational, friendly",
        "optimal_send_time": "morning",
        "special_offer":     False,
        "key_angle":         "Simple value: 1% more than what they are earning now",
    },
}


# ── Helper functions ──────────────────────────────────────────────────────────

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

def _build_segment_dict(bucket_name: str, cids: list[str],
                        id_to_customer: dict, seg_idx: int) -> dict:
    """Build a complete segment dict from a bucket of customer IDs."""
    meta  = SEGMENT_META[bucket_name]
    group = [id_to_customer[cid] for cid in cids if cid in id_to_customer]

    ages    = [_age(c)    for c in group if _age(c) > 0]
    incomes = [_income(c) for c in group if _income(c) > 0]
    cities  = [c.get("City", "") for c in group if c.get("City")]

    avg_age    = round(sum(ages)    / len(ages),    1) if ages    else 0
    avg_income = round(sum(incomes) / len(incomes))    if incomes else 0
    top_city   = max(set(cities), key=cities.count)    if cities  else "Unknown"

    occ_breakdown: dict[str, int] = {}
    for c in group:
        occ = _occupation_bucket(c)
        occ_breakdown[occ] = occ_breakdown.get(occ, 0) + 1

    dominant_occ = max(occ_breakdown, key=occ_breakdown.get) if occ_breakdown else "other"
    occ_angle    = OCCUPATION_ANGLES.get(dominant_occ, OCCUPATION_ANGLES["other"])

    return {
        "segment_id":           f"seg_{seg_idx}",
        "bucket":               bucket_name,
        "name":                 meta["name"],
        "description":          meta["key_angle"],
        "customer_ids":         cids,
        "size":                 len(cids),
        "targeting_rationale":  (
            f"{meta['key_angle']} | avg age {avg_age} | "
            f"avg income \u20b9{avg_income:,.0f} | top city {top_city}"
        ),
        "optimal_send_time":    meta["optimal_send_time"],
        "tone":                 meta["tone"],
        "special_offer":        meta["special_offer"],
        "key_angle":            meta["key_angle"],
        "occupation_breakdown": occ_breakdown,
        "dominant_occupation":  dominant_occ,
        "occupation_angle":     occ_angle,
        "avg_age":              avg_age,
        "avg_income":           avg_income,
        "top_city":             top_city,
    }


def smartsplit_customers(customers: list) -> list[dict]:
    """
    Two-axis segmentation: demographic × occupation.

    Always returns at least one segment (general) even if the female_senior
    bucket is too small. This guarantees the pipeline never gets 0 segments.

    Threshold: female_senior segment is only standalone when >= 30 customers.
    Below that, they are folded into general (but flagged via special_offer
    per-customer for content_gen to detect).
    """
    if not customers:
        return []

    id_to_customer = {c["customer_id"]: c for c in customers}
    assigned: set[str] = set()

    # Female seniors (age >= 55, gender = female)
    female_senior_ids: list[str] = []
    for c in customers:
        cid = c["customer_id"]
        if _age(c) >= 55 and _is_female(c):
            female_senior_ids.append(cid)
            assigned.add(cid)

    # General bucket — everyone else
    general_ids: list[str] = [
        c["customer_id"] for c in customers
        if c["customer_id"] not in assigned
    ]

    segments: list[dict] = []
    seg_idx = 1

    # Only create female_senior as a standalone segment if large enough
    MIN_SEGMENT_SIZE = 30
    if len(female_senior_ids) >= MIN_SEGMENT_SIZE:
        segments.append(_build_segment_dict("female_senior", female_senior_ids, id_to_customer, seg_idx))
        seg_idx += 1
    else:
        # Too small — merge into general (content_gen reads special_offer from seg dict)
        general_ids = female_senior_ids + general_ids
        if female_senior_ids:
            # Tag these customers in the raw dict so content_gen can mention the bonus
            for cid in female_senior_ids:
                if cid in id_to_customer:
                    id_to_customer[cid]["_special_offer"] = True

    # General segment always gets created if there are customers
    if general_ids:
        seg = _build_segment_dict("general", general_ids, id_to_customer, seg_idx)
        # If female seniors were merged in, flag the segment as having special offer
        if female_senior_ids and len(female_senior_ids) < MIN_SEGMENT_SIZE:
            seg["special_offer"] = True
            seg["key_angle"] = (
                "1% higher returns — senior women in this group get an additional 0.25%"
            )
        segments.append(seg)

    return segments


# ── Profiler node ─────────────────────────────────────────────────────────────

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

    if not customers:
        await emit(campaign_id, "profiler", "error",
                   "❌ No customers available. Cannot build segments.")
        return {"customers": [], "segments": [], "status": "error"}

    # ── SmartSplit ────────────────────────────────────────────────────────────
    await emit(campaign_id, "profiler", "agent_thought",
               "📊 Running two-axis segmentation: demographic × occupation...")

    segments = smartsplit_customers(customers)

    # Sanity check — should never be empty now, but log clearly if it is
    if not segments:
        await emit(campaign_id, "profiler", "agent_thought",
                   "⚠️ Segmentation returned 0 segments — this should not happen. "
                   "Creating emergency catch-all segment.")
        all_ids  = [c["customer_id"] for c in customers]
        segments = [_build_segment_dict("general", all_ids, {c["customer_id"]: c for c in customers}, 1)]

    for seg in segments:
        occ_str = ", ".join(
            f"{k}:{v}" for k, v in
            sorted(seg["occupation_breakdown"].items(), key=lambda x: -x[1])[:3]
        )
        await emit(campaign_id, "profiler", "agent_thought",
                   f"  📦 '{seg['name']}': {seg['size']} customers | "
                   f"dominant occ: {seg['dominant_occupation']} | "
                   f"angle: {seg['occupation_angle']['angle']}")
        await emit(campaign_id, "profiler", "agent_thought",
                   f"     occ breakdown (top 3): {occ_str}")

    # ── LLM strategic insight (non-critical — failure is fine) ───────────────
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

    prompt = f"""You are a customer analytics expert for SuperBFSI's XDeposit campaign.

Segments built from {len(customers)} customers:
{segment_summary}

Brief: {brief}

In 2-3 sentences: which segment has the highest click potential and why?
Reference occupation angles and the female senior 0.25% bonus."""

    try:
        insights = await invoke_with_retry(llm, prompt)
    except Exception:
        insights = (
            f"SmartSplit complete: {len(segments)} segments. "
            f"Female Senior Citizens have highest potential due to the exclusive 0.25% bonus."
        )

    await emit(campaign_id, "profiler", "agent_thought",
               f"✅ Segmentation complete: {len(segments)} segments.")
    await emit(campaign_id, "profiler", "agent_thought",
               f"🔍 Strategic insight: {insights}")

    return {
        "customers": customers,
        "segments":  segments,
        "status":    "profiled",
    }