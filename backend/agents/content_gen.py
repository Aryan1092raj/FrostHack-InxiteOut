"""
content_gen.py — Email content generation.

Root fixes in this rewrite:
  1. Fallback templates use proper Unicode codepoints (\\U0001F449) not surrogates.
  2. No markdown ** in body — HTML <b> only so email clients render correctly.
  3. Prompt bans FOMO language, enforces 120-word limit, enforces <b> not **.
  4. Customer ID resolution deduplicates across variants before any send.
  5. Surrogate stripping removed here — base.py invoke_with_retry handles it.
  6. Segment context only built from segments the variant actually covers.
"""

import json
import random
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json, invoke_with_retry

XDEPOSIT_URL = "https://superbfsi.com/xdeposit/explore/"

# ── Fallback templates ────────────────────────────────────────────────────────
# Use proper Unicode codepoints — NOT surrogate pairs like \ud83d\udc49
FALLBACK_TEMPLATES = [
    {
        "subject": "Your FD is earning 1% less than it should",
        "body": (
            f"Hi,\n\n"
            f"Your fixed deposit could be working harder for you.\n\n"
            f"\U0001F449 <a href=\"{XDEPOSIT_URL}\">See what XDeposit pays you</a>\n\n"
            f"XDeposit from SuperBFSI gives you <b>1% higher returns</b> than most competitors "
            f"\u2014 that\u2019s \u20b91,000 extra per year on every \u20b91 lakh deposited.\n\n"
            f"Senior women get an <b>additional 0.25%</b> on top.\n\n"
            f"No lock-in surprises. RBI-regulated.\n\n"
            f"\U0001F449 {XDEPOSIT_URL}\n\n"
            f"\u2014 SuperBFSI Team"
        ),
    },
    {
        "subject": "Is your money earning what it deserves?",
        "body": (
            f"Hi,\n\n"
            f"\U0001F449 <a href=\"{XDEPOSIT_URL}\">Calculate your XDeposit earnings</a>\n\n"
            f"Most FDs pay the same rate they did years ago. XDeposit pays "
            f"<b>1 percentage point more</b> \u2014 and for senior women, "
            f"an extra 0.25% on top of that.\n\n"
            f"Same safety. Same guarantee. More return.\n\n"
            f"\U0001F449 {XDEPOSIT_URL}\n\n"
            f"\u2014 SuperBFSI"
        ),
    },
]


async def content_gen_node(state: CampaignState) -> dict:
    campaign_id      = state["campaign_id"]
    brief            = state["brief"]
    strategy         = state["strategy"]
    segments         = state.get("segments", [])
    iteration        = state.get("iteration", 1)
    rejection_reason = state.get("rejection_reason", "")
    winning_variant  = state.get("winning_variant_info", {})
    dna_rules        = state.get("dna_content_rules", "")
    thompson_winner  = state.get("thompson_winner", {})
    opt_subject      = state.get("opt_subject_strategy", "")
    opt_content      = state.get("opt_content_adjustments", "")

    await emit(campaign_id, "content_gen", "agent_thought",
               f"Generating email content (iteration {iteration})...")

    if dna_rules:
        await emit(campaign_id, "content_gen", "agent_thought",
                   "🧬 DNA-constrained writing active.")

    variants = strategy.get("ab_variants", [])
    seg_map  = {s["segment_id"]: s for s in segments}
    llm      = get_llm(temperature=0.6)
    emails   = []

    # Track customer IDs used across ALL variants this iteration
    # to prevent the same customer getting emailed twice
    used_customer_ids: set[str] = set()

    for variant in variants:
        variant_id          = variant.get("variant_id", "variant_a")
        segment_ids         = variant.get("segment_ids", [])
        send_time           = variant.get("send_time", "")
        tone                = variant.get("tone", "informational, friendly")
        include_emoji       = variant.get("include_emoji", True)
        include_url         = variant.get("include_url", True)
        direct_customer_ids = variant.get("direct_customer_ids", [])
        strategy_notes      = variant.get("strategy_notes", "")

        # ── Resolve customer IDs ──────────────────────────────────────────────
        if direct_customer_ids:
            raw_ids = list(direct_customer_ids)
        else:
            raw_ids = []
            for sid in segment_ids:
                seg = seg_map.get(sid)
                if seg:
                    raw_ids.extend(seg.get("customer_ids", []))

        # Deduplicate within this variant and across variants
        customer_ids = []
        for cid in raw_ids:
            if cid not in used_customer_ids:
                customer_ids.append(cid)
                used_customer_ids.add(cid)

        if not customer_ids:
            await emit(campaign_id, "content_gen", "agent_thought",
                       f"⚠️ {variant_id} has no customers after dedup — skipping.")
            continue

        await emit(campaign_id, "content_gen", "agent_thought",
                   f"Writing {variant_id} for {len(customer_ids)} customers "
                   f"(tone: {tone}, emoji: {include_emoji})...")

        # ── Segment context ───────────────────────────────────────────────────
        seg_descriptions  = []
        has_special_offer = False
        occupation_hints  = []

        for sid in segment_ids:
            seg = seg_map.get(sid)
            if not seg:
                continue
            parts = [f"- {seg['name']} ({seg['size']} customers"]
            if seg.get("avg_age"):
                parts.append(f"avg age {seg['avg_age']}")
            if seg.get("top_city"):
                parts.append(f"top city {seg['top_city']}")
            parts.append(f"angle: {seg.get('key_angle', '')}")
            seg_descriptions.append(", ".join(parts) + ")")

            if seg.get("special_offer"):
                has_special_offer = True

            occ_angle = seg.get("occupation_angle", {})
            if occ_angle.get("trigger"):
                occupation_hints.append(
                    f"  Occupation trigger: '{occ_angle['trigger']}' → "
                    f"message: '{occ_angle['message']}'"
                )

        # ── Prompt blocks ─────────────────────────────────────────────────────
        special_offer_block = ""
        if has_special_offer:
            special_offer_block = (
                "\n\U0001F31F MANDATORY for this segment: The FIRST sentence of the body "
                "MUST mention the EXTRA 0.25 percentage point bonus for female senior citizens. "
                "This is their exclusive offer.\n"
            )

        occupation_block = ""
        if occupation_hints:
            occupation_block = (
                "\nOccupation psychology for this segment:\n"
                + "\n".join(occupation_hints) + "\n"
            )

        thompson_block = ""
        if thompson_winner and thompson_winner.get("subject"):
            thompson_block = (
                f"\n\U0001F3C6 PROVEN WINNER from probe phase — REPLICATE this formula:\n"
                f"  Subject structure: '{thompson_winner['subject'][:80]}'\n"
                f"  Tone: {thompson_winner.get('tone', '')}\n"
                f"  Dimension that won: {thompson_winner.get('dimension', '')}\n"
                f"  Click rate: {thompson_winner.get('click_rate', 0):.1%}\n"
                f"  → variant_a MUST follow this exact formula. Only change the wording slightly.\n"
            )

        optimizer_block = ""
        if iteration > 1 and (opt_subject or opt_content):
            optimizer_block = (
                f"\n\U000026A0 OPTIMIZER DIRECTIVES (from previous iteration analysis):\n"
                f"  Subject format: {opt_subject}\n"
                f"  Body changes: {opt_content}\n"
                f"  Apply these — they are based on real click data.\n"
            )

        strategy_block = ""
        if strategy_notes:
            strategy_block = (
                f"\n\U0001F4CB VARIANT EXECUTION NOTES (hard requirements from strategist):\n"
                f"  {strategy_notes}\n"
                f"  Follow these notes exactly.\n"
            )

        winning_block = ""
        if winning_variant and winning_variant.get("tone") and iteration >= 2:
            winning_tone  = winning_variant["tone"]
            winning_click = winning_variant.get("click_rate", 0)
            if tone == winning_tone:
                winning_block = (
                    f"\n\U0001F512 TONE LOCK: '{winning_tone}' achieved {winning_click:.1%} click rate. "
                    f"This variant MUST use tone: '{winning_tone}'. Do NOT deviate.\n"
                )
            else:
                winning_block = (
                    f"\n\U0001F9EA CHALLENGER TONE: the previous winning tone was '{winning_tone}', "
                    f"but this variant MUST stay in the alternate tone '{tone}' for learning. "
                    f"Do NOT drift back to the winning tone.\n"
                )

        seed_block = ""
        seed = FALLBACK_TEMPLATES[0] if has_special_offer else random.choice(FALLBACK_TEMPLATES)
        seed_block = (
            f"\nSeed template (improve on this — do NOT copy verbatim):\n"
            f"  Subject: {seed['subject']}\n"
        )

        # ── Build prompt ──────────────────────────────────────────────────────
        prompt = f"""You are an expert email copywriter for SuperBFSI's XDeposit campaign.

Campaign Brief: {brief}

Product:
- XDeposit gives 1 percentage point HIGHER returns than ALL competitors
- Female senior citizens get EXTRA 0.25 percentage point on top
- CTA URL (the ONLY URL allowed): {XDEPOSIT_URL}

Target Segments:
{chr(10).join(seg_descriptions) if seg_descriptions else "General cohort"}
{special_offer_block}
{occupation_block}
{thompson_block}
{optimizer_block}
{strategy_block}
{winning_block}
{seed_block}

Variant Style:
- Tone: {tone}
- Include emojis: {include_emoji}
- Rejection feedback to address: {rejection_reason or 'None'}

{dna_rules if dna_rules else ''}

STRICT EMAIL RULES:
- Subject: plain text, max 200 chars, NO URLs
- Body: MAXIMUM 80 WORDS — hard limit, count them
- Line 1 of body: the CTA link — no preamble before it
  Example: "👉 Your FD is losing 1% yearly. See what XDeposit pays: {XDEPOSIT_URL}"
- Line 2: one sentence with the specific number (₹1,000 extra per lakh/year)
- Line 3: one trust signal (RBI-regulated / no lock-in surprises)
- Final line: repeat CTA URL bare
- NO: long paragraphs, company history, "we are excited", generic phrases
- BANNED PHRASES: "don't miss out", "act now", "limited time", "exciting opportunity"
- Formatting: <b>key numbers only</b> — do not bold entire sentences
- BANNED: markdown asterisks **text** — use <b>text</b> only
- Use this structure exactly:
  1. CTA + benefit in sentence 1
  2. Specific numeric payoff sentence
  3. One trust/reassurance sentence
  4. Bare CTA URL on the final line

Return ONLY valid JSON — no markdown, no backticks, no explanation:
{{"subject": "your subject here", "body": "your body here"}}"""

        # ── Call LLM ──────────────────────────────────────────────────────────
        try:
            raw     = await invoke_with_retry(llm, prompt)
            parsed  = json.loads(clean_llm_json(raw), strict=False)
            subject = str(parsed.get("subject", "")).strip()[:200]
            body    = str(parsed.get("body", "")).strip()[:5000]

            if not subject or not body:
                raise ValueError("LLM returned empty subject or body")

            # Ensure CTA is present
            if include_url and XDEPOSIT_URL not in body:
                body += f"\n\n\U0001F449 {XDEPOSIT_URL}"

            await emit(campaign_id, "content_gen", "agent_thought",
                       f"✅ {variant_id}: '{subject[:70]}'")

        except Exception as e:
            await emit(campaign_id, "content_gen", "agent_thought",
                       f"⚠️ LLM failed for {variant_id} ({str(e)[:100]}). Using fallback.")
            tmpl    = FALLBACK_TEMPLATES[0] if has_special_offer else random.choice(FALLBACK_TEMPLATES)
            subject = tmpl["subject"]
            body    = tmpl["body"]

        emails.append({
            "variant":      variant_id,
            "subject":      subject,
            "body":         body,
            "customer_ids": customer_ids,
            "send_time":    send_time,
            "tone":         tone,
            "strategy_notes": strategy_notes,
            "segment_ids":  segment_ids,
        })

    if not emails:
        await emit(campaign_id, "content_gen", "agent_thought",
                   "❌ No emails generated.")
    else:
        await emit(campaign_id, "content_gen", "agent_thought",
                   f"✅ Generated {len(emails)} email variants.")

    return {"emails": emails, "status": "content_ready"}
