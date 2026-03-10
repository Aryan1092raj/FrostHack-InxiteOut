"""
Content Gen — Updated to use:
  Innovation #2: Email DNA winning pattern (hard constraints from probe correlation)
  Innovation #3: Occupation angle per segment (psychological messaging)
  Innovation #1: Thompson winner context (don't repeat losers' patterns)
"""

import json
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json, invoke_with_retry

XDEPOSIT_URL = "https://superbfsi.com/xdeposit/explore/"


async def content_gen_node(state: CampaignState) -> dict:
    campaign_id     = state["campaign_id"]
    brief           = state["brief"]
    strategy        = state["strategy"]
    segments        = state.get("segments", [])
    iteration       = state.get("iteration", 1)
    rejection_reason = state.get("rejection_reason", "")
    winning_variant = state.get("winning_variant_info", {})
    dna_rules       = state.get("dna_content_rules", "")   # Innovation #2
    thompson_winner = state.get("thompson_winner", {})     # Innovation #1

    await emit(campaign_id, "content_gen", "agent_thought",
               f"Generating email content (iteration {iteration})...")

    if dna_rules:
        await emit(campaign_id, "content_gen", "agent_thought",
                   "🧬 DNA-constrained writing active — using probe-learned signal.")
    if thompson_winner:
        await emit(campaign_id, "content_gen", "agent_thought",
                   f"🏆 Thompson winner context loaded: '{thompson_winner.get('probe_id')}' "
                   f"(click: {thompson_winner.get('click_rate', 0):.1%})")

    variants = strategy.get("ab_variants", [])
    seg_map  = {s["segment_id"]: s for s in segments}

    llm    = get_llm(temperature=0.6)
    emails = []

    for variant in variants:
        variant_id         = variant.get("variant_id", "variant_a")
        segment_ids        = variant.get("segment_ids", [])
        send_time          = variant.get("send_time", "")
        tone               = variant.get("tone", "professional")
        include_emoji      = variant.get("include_emoji", True)
        include_url        = variant.get("include_url", True)
        direct_customer_ids = variant.get("direct_customer_ids", [])

        # Resolve customer IDs
        if direct_customer_ids:
            customer_ids = direct_customer_ids
        else:
            customer_ids = []
            for sid in segment_ids:
                seg = seg_map.get(sid)
                if seg:
                    customer_ids.extend(seg.get("customer_ids", []))

        if not customer_ids:
            await emit(campaign_id, "content_gen", "agent_thought",
                       f"⚠️  {variant_id} has no customers — skipping.")
            continue

        await emit(campaign_id, "content_gen", "agent_thought",
                   f"Writing {variant_id} for {len(customer_ids)} customers "
                   f"(tone: {tone}, emoji: {include_emoji})...")

        # ── Build rich segment context ─────────────────────────────────────────
        seg_descriptions   = []
        has_special_offer  = False
        occupation_angles  = []

        for sid in segment_ids:
            seg = seg_map.get(sid)
            if not seg:
                continue

            desc = f"- {seg['name']} ({seg['size']} customers"
            if seg.get("avg_age"):
                desc += f", avg age {seg['avg_age']}"
            if seg.get("avg_income"):
                desc += f", avg income ₹{seg['avg_income']:,.0f}"
            if seg.get("top_city"):
                desc += f", top city {seg['top_city']}"
            desc += f") — angle: {seg.get('key_angle', '')}"
            seg_descriptions.append(desc)

            if seg.get("special_offer"):
                has_special_offer = True

            # Innovation #3: include occupation psychological angle
            occ_angle = seg.get("occupation_angle", {})
            if occ_angle and occ_angle.get("trigger"):
                occupation_angles.append(
                    f"{seg['dominant_occupation']}: trigger='{occ_angle['trigger']}', "
                    f"message='{occ_angle['message']}'"
                )

        special_offer_block = ""
        if has_special_offer:
            special_offer_block = (
                "\n🌟 MANDATORY: This segment contains FEMALE SENIOR CITIZENS. "
                "You MUST prominently mention the EXTRA 0.25 percentage point bonus "
                "for female senior citizens in the FIRST SENTENCE of the body. "
                "This is their unique exclusive benefit — open with it.\n"
            )

        occupation_block = ""
        if occupation_angles:
            occupation_block = (
                "\nOccupation Psychology (use these psychological triggers in body copy):\n"
                + "\n".join(f"  • {a}" for a in occupation_angles)
                + "\n"
            )

        # Innovation #1: Thompson winner context
        thompson_block = ""
        if thompson_winner and iteration == 1:
            thompson_block = (
                f"\n🏆 PROBE WINNER CONTEXT (do NOT copy — use as inspiration for what works):\n"
                f"  Winning probe: {thompson_winner.get('probe_id')} | "
                f"dimension: {thompson_winner.get('dimension')}\n"
                f"  Winning subject: '{thompson_winner.get('subject', '')[:60]}'\n"
                f"  Click rate achieved: {thompson_winner.get('click_rate', 0):.1%}\n"
            )
        elif winning_variant and iteration > 1:
            thompson_block = (
                f"\n🏆 PREVIOUS WINNING SUBJECT: '{winning_variant.get('subject', '')[:70]}'\n"
                f"   Use a DIFFERENT subject format — don't repeat the same structure.\n"
            )

        prompt = f"""You are an expert email copywriter for SuperBFSI, an Indian BFSI company.

Campaign Brief: {brief}

Product: XDeposit Term Deposit
- 1 percentage point HIGHER returns than ALL competitors
- EXTRA 0.25 percentage point EXCLUSIVELY for female senior citizens
- CTA URL (only allowed URL): {XDEPOSIT_URL}

Target Segments:
{chr(10).join(seg_descriptions)}
{special_offer_block}
{occupation_block}
{thompson_block}

Variant Style:
- Tone: {tone}
- Include emojis: {include_emoji}
- Rejection feedback: {rejection_reason or 'None'}
- BANNED: urgency, scarcity, FOMO — the API penalises this
- Preferred tones: trust-building, aspirational, informational, warm/personal

{dna_rules if dna_rules else ''}

Email Rules (STRICT):
- Subject: plain English only, max 200 chars, NO URLs
- Body: English text + emojis + {XDEPOSIT_URL} ONLY — max 5000 chars
- Use bold **text**, italic _text_, underline <u>text</u>
- CTA URL must appear at LEAST twice — in the FIRST 2 sentences AND at the end
- Click rate is the #1 goal — make every sentence push toward the CTA

Return ONLY valid JSON (no markdown, no backticks):
{{"subject": "Your subject here", "body": "Your body here"}}"""

        try:
            raw     = await invoke_with_retry(llm, prompt)
            content = json.loads(clean_llm_json(raw), strict=False)
            subject = content.get("subject", "")[:200]
            body    = content.get("body", "")[:5000]

            # Enforce CTA presence
            if include_url and XDEPOSIT_URL not in body:
                body += f"\n\n👉 Explore XDeposit now: {XDEPOSIT_URL}"

            await emit(campaign_id, "content_gen", "agent_thought",
                       f"✅ {variant_id}: '{subject[:60]}...'")

        except Exception as e:
            await emit(campaign_id, "content_gen", "agent_thought",
                       f"⚠️  Content fallback for {variant_id}: {str(e)[:80]}")
            subject = f"XDeposit — Earn 1% More with SuperBFSI"
            body    = (
                f"Dear Customer,\n\n"
                f"We're excited to introduce **XDeposit**, SuperBFSI's flagship term deposit "
                f"giving you **1% higher returns** than competitors.\n\n"
                f"👉 Explore XDeposit: {XDEPOSIT_URL}\n\n"
                f"🌟 Female senior citizens get an **additional 0.25%** bonus rate!\n\n"
                f"**Your savings deserve better.** Start today.\n\n"
                f"👉 {XDEPOSIT_URL}\n\n"
                f"Warm regards,\nSuperBFSI Team"
            )

        emails.append({
            "variant":      variant_id,
            "subject":      subject,
            "body":         body,
            "customer_ids": customer_ids,
            "send_time":    send_time,
            "tone":         tone,
            "segment_ids":  segment_ids,
        })

    if not emails:
        await emit(campaign_id, "content_gen", "agent_thought",
                   "❌ No emails generated. Check strategy variants.")

    await emit(campaign_id, "content_gen", "agent_thought",
               f"✅ Generated {len(emails)} email variants.")

    return {"emails": emails, "status": "content_ready"}
