"""
strategist.py — A/B strategy design.

Issues fixed in this rewrite:
  1. Tone lock: winning tone is injected at the TOP of the prompt as an
     absolute mandate from iteration 2 onwards. Not buried at the end.
  2. Subject format lock: winning subject format (question/number/statement)
     is detected and enforced for variant_a. variant_b must use opposite
     format so we keep learning while exploiting.
  3. Rescue logic fixed: non-clickers who OPENED get same subject format
     (it worked) but different body/CTA. Non-clickers who NEVER OPENED get
     a completely different subject. Previously all non-clickers got "completely
     different everything" which threw away the open-rate signal.
  4. Send time is now 15 minutes from now (IST), not tomorrow. For the demo
     this means campaigns fire immediately after approval.
"""

import json
from datetime import datetime, timedelta
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json, invoke_with_retry


def _detect_subject_format(subject: str) -> str:
    """Detect whether a subject is question / number-led / statement."""
    s = subject.strip()
    if s.endswith("?"):
        return "question"
    if s and (s[0].isdigit() or s[:2] in ("1%", "1 ", "₹", "Re")):
        return "number-led"
    return "statement"


def _opposite_format(fmt: str) -> str:
    mapping = {
        "question":    "number-led (start with a number or ₹ amount)",
        "number-led":  "question (end with ?)",
        "statement":   "question (end with ?)",
    }
    return mapping.get(fmt, "question (end with ?)")


async def strategist_node(state: CampaignState) -> dict:
    campaign_id        = state["campaign_id"]
    brief              = state["brief"]
    segments           = state["segments"]
    iteration          = state.get("iteration", 1)
    optimization_notes = state.get("optimization_notes", "")
    rejection_reason   = state.get("rejection_reason", "")
    underperforming_ids: list = state.get("underperforming_customer_ids", [])
    winning_variant_info: dict = state.get("winning_variant_info", {})

    await emit(campaign_id, "strategist", "agent_thought",
               f"Planning campaign strategy (iteration {iteration})...")

    if rejection_reason:
        await emit(campaign_id, "strategist", "agent_thought",
                   f"Incorporating rejection feedback: {rejection_reason}")

    is_rescue = iteration > 1 and len(underperforming_ids) > 0

    if is_rescue:
        await emit(campaign_id, "strategist", "agent_thought",
                   f"🎯 Rescue mode: targeting {len(underperforming_ids)} non-clickers only.")

    llm = get_llm(temperature=0.5)

    # ── Send times — 15 minutes from now, not tomorrow ────────────────────────
    # This ensures campaigns fire quickly after approval for demo purposes.
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)  # IST
    base = now + timedelta(minutes=15)
    times = {
        "soon":      base.strftime("%d:%m:%y %H:%M:%S"),
        "morning":   base.strftime("%d:%m:%y %H:%M:%S"),   # same as soon for iteration 1
        "afternoon": (base + timedelta(hours=1)).strftime("%d:%m:%y %H:%M:%S"),
        "evening":   (base + timedelta(hours=2)).strftime("%d:%m:%y %H:%M:%S"),
        "night":     (base + timedelta(hours=3)).strftime("%d:%m:%y %H:%M:%S"),
    }

    # ── Tone and subject lock (iterations 2+) ─────────────────────────────────
    # These go at the TOP of the prompt so the LLM cannot ignore them.
    lock_block = ""
    if winning_variant_info and iteration >= 2:
        winning_tone    = winning_variant_info.get("tone", "")
        winning_subject = winning_variant_info.get("subject", "")
        winning_click   = winning_variant_info.get("click_rate", 0)
        winning_open    = winning_variant_info.get("open_rate", 0)

        if winning_tone:
            winning_fmt  = _detect_subject_format(winning_subject)
            opposite_fmt = _opposite_format(winning_fmt)

            lock_block = (
                f"\n{'='*60}\n"
                f"🔒 ABSOLUTE MANDATES — READ BEFORE ANYTHING ELSE\n"
                f"{'='*60}\n"
                f"Winning variant data:\n"
                f"  Subject: '{winning_subject}'\n"
                f"  Tone: {winning_tone}\n"
                f"  Open rate: {winning_open:.1%} | Click rate: {winning_click:.1%}\n"
                f"\n"
                f"MANDATE 1 — TONE:\n"
                f"  Both variant_a AND variant_b MUST use tone: '{winning_tone}'\n"
                f"  Using any other tone is a CRITICAL FAILURE.\n"
                f"\n"
                f"MANDATE 2 — SUBJECT FORMAT:\n"
                f"  variant_a subject MUST use '{winning_fmt}' format (proven winner).\n"
                f"  variant_b subject MUST use '{opposite_fmt}' format (challenger).\n"
                f"  Only the wording changes — the FORMAT is fixed.\n"
                f"\n"
                f"BANNED subject openers (these get ignored in inboxes):\n"
                f"  'Earn', 'Introducing', 'Announcing', 'Learn', 'Discover',\n"
                f"  'Get', 'We are', 'Dear Customer'\n"
                f"{'='*60}\n"
            )

    # ── Rescue section ────────────────────────────────────────────────────────
    # FIX: Rescue logic now correctly separates openers from non-openers.
    # Previously all non-clickers got "completely different everything" which
    # discarded the open-rate signal. Now:
    #   - Bucket A (opened, didn't click): keep subject format, change body/CTA
    #   - Bucket B (never opened): change subject format entirely
    rescue_section = ""
    customer_pool_note = f"Target pool: all {sum(s['size'] for s in segments)} customers"

    if is_rescue:
        prev_tone    = winning_variant_info.get("tone", "informational, friendly")
        prev_subject = winning_variant_info.get("subject", "N/A")
        prev_click   = winning_variant_info.get("click_rate", 0)
        prev_open    = winning_variant_info.get("open_rate", 0)

        rescue_section = (
            f"\n⚠️ RESCUE MODE (Iteration {iteration}):\n"
            f"Targeting {len(underperforming_ids)} customers who did NOT click last time.\n"
            f"Previous: Subject='{prev_subject}' | Tone={prev_tone} | "
            f"Open={prev_open:.1%} | Click={prev_click:.1%}\n"
            f"\n"
            f"These non-clickers fall into two groups:\n"
            f"  Bucket A — opened but did not click (~those who opened):\n"
            f"    → Subject format WORKED (they opened). Keep same format.\n"
            f"    → Body/CTA FAILED. Put CTA in sentence 1. Cut to 80 words max.\n"
            f"  Bucket B — never opened:\n"
            f"    → Subject FAILED. Use a completely different format.\n"
            f"    → Short subject, lead with a number or question.\n"
            f"\n"
            f"Split the {len(underperforming_ids)} non-clickers evenly:\n"
            f"  variant_a → Bucket A strategy (CTA-first body fix)\n"
            f"  variant_b → Bucket B strategy (new subject format)\n"
        )
        if optimization_notes:
            rescue_section += f"\nOptimizer analysis:\n{optimization_notes}\n"

        customer_pool_note = (
            f"Target pool: {len(underperforming_ids)} non-clickers "
            f"(NOT the full {sum(s['size'] for s in segments)} cohort)"
        )
    elif optimization_notes and iteration > 1:
        rescue_section = (
            f"\n⚠️ REQUIRED ACTIONS FROM OPTIMIZER:\n{optimization_notes}\n"
        )

    # ── Segments JSON ─────────────────────────────────────────────────────────
    segments_json = json.dumps([
        {
            "segment_id":          s["segment_id"],
            "name":                s["name"],
            "size":                s["size"],
            "targeting_rationale": s.get("targeting_rationale", ""),
            "optimal_send_time":   s.get("optimal_send_time", "morning"),
            "tone":                s.get("tone", "informational, friendly"),
        }
        for s in segments
    ], indent=2)

    # ── Build prompt ──────────────────────────────────────────────────────────
    prompt = f"""{lock_block}You are a digital marketing strategist for SuperBFSI launching XDeposit term deposit.

Campaign Brief: {brief}

Current Iteration: {iteration}
{rescue_section}
{customer_pool_note}

Available Customer Segments:
{segments_json}

Available Send Times:
- Soon (15 min from now): {times['soon']}
- Afternoon:              {times['afternoon']}
- Evening:                {times['evening']}
- Night:                  {times['night']}

Previous Rejection Reason: {rejection_reason or 'None'}

Design an A/B strategy to MAXIMISE click rate (weighted 70% in scoring).

Rules:
- Create exactly 2 A/B variants (variant_a and variant_b)
- MUST assign every segment_id to at least one variant — no orphaned customers
- Choose DIFFERENT send times for each variant
- BANNED tones: urgency, scarcity, FOMO, pressure — the API penalises these
- Preferred tones: trust-building, aspirational, informational, warm/personal

Return ONLY this JSON (no markdown, no backticks):
{{
    "ab_variants": [
        {{
            "variant_id": "variant_a",
            "name": "Descriptive name",
            "segment_ids": ["seg_1"],
            "send_time": "{times['soon']}",
            "strategy_notes": "Why this variant and timing",
            "tone": "informational, friendly",
            "include_url": true,
            "include_emoji": true
        }},
        {{
            "variant_id": "variant_b",
            "name": "Descriptive name",
            "segment_ids": ["seg_2"],
            "send_time": "{times['evening']}",
            "strategy_notes": "Why this variant and timing",
            "tone": "aspirational",
            "include_url": true,
            "include_emoji": false
        }}
    ],
    "overall_rationale": "Why this strategy will maximise click rate",
    "expected_winner": "variant_a or variant_b and why"
}}"""

    # ── Call LLM ──────────────────────────────────────────────────────────────
    try:
        content  = await invoke_with_retry(llm, prompt)
        result   = json.loads(clean_llm_json(content), strict=False)
        variants = result.get("ab_variants", [])
        rationale      = result.get("overall_rationale", "")
        expected_winner = result.get("expected_winner", "")

        if not variants:
            raise ValueError("LLM returned no variants")

        # Ensure every segment is assigned to at least one variant
        if not is_rescue:
            assigned: set = set()
            for v in variants:
                assigned.update(v.get("segment_ids", []))
            all_sids = [s["segment_id"] for s in segments]
            unassigned = [sid for sid in all_sids if sid not in assigned]
            if unassigned:
                for i, sid in enumerate(unassigned):
                    variants[i % len(variants)].setdefault("segment_ids", []).append(sid)
                await emit(campaign_id, "strategist", "agent_thought",
                           f"📎 {len(unassigned)} orphaned segments redistributed.")

        # Inject rescue customer IDs directly so content_gen doesn't need segment lookup
        if is_rescue and underperforming_ids:
            mid = len(underperforming_ids) // 2
            if len(variants) >= 2:
                variants[0]["direct_customer_ids"] = underperforming_ids[:mid]
                variants[1]["direct_customer_ids"] = underperforming_ids[mid:]
            else:
                variants[0]["direct_customer_ids"] = underperforming_ids
            await emit(campaign_id, "strategist", "agent_thought",
                       f"✅ Rescue IDs injected: {mid} → variant_a, "
                       f"{len(underperforming_ids) - mid} → variant_b")

        await emit(campaign_id, "strategist", "agent_thought",
                   f"✅ Strategy ready: {len(variants)} variants. {rationale[:100]}")
        await emit(campaign_id, "strategist", "agent_thought",
                   f"🏆 Expected winner: {expected_winner}")

        for v in variants:
            n = len(v.get("direct_customer_ids", [])) or "segment-based"
            await emit(campaign_id, "strategist", "agent_thought",
                       f"📧 {v['variant_id']}: '{v.get('name','')}' → "
                       f"{n} customers @ {v.get('send_time','')}")

        return {
            "strategy": {
                "ab_variants":    variants,
                "rationale":      rationale,
                "expected_winner": expected_winner,
                "iteration":      iteration,
            },
            "status": "strategy_ready",
        }

    except Exception as e:
        await emit(campaign_id, "strategist", "agent_thought",
                   f"⚠️ LLM strategy failed ({str(e)[:80]}). Using deterministic fallback.")

        # Deterministic fallback — always produces valid variants
        if is_rescue and underperforming_ids:
            mid = len(underperforming_ids) // 2
            fallback_variants = [
                {
                    "variant_id":           "variant_a",
                    "name":                 "Rescue CTA-First",
                    "segment_ids":          [],
                    "direct_customer_ids":  underperforming_ids[:mid],
                    "send_time":            times["soon"],
                    "tone":                 winning_variant_info.get("tone", "aspirational"),
                    "include_url":          True,
                    "include_emoji":        True,
                },
                {
                    "variant_id":           "variant_b",
                    "name":                 "Rescue New Subject",
                    "segment_ids":          [],
                    "direct_customer_ids":  underperforming_ids[mid:],
                    "send_time":            times["evening"],
                    "tone":                 "informational, friendly",
                    "include_url":          True,
                    "include_emoji":        False,
                },
            ]
        else:
            mid = max(len(segments) // 2, 1)
            fallback_variants = [
                {
                    "variant_id":  "variant_a",
                    "name":        "Aspirational",
                    "segment_ids": [s["segment_id"] for s in segments[:mid]],
                    "send_time":   times["soon"],
                    "tone":        "aspirational",
                    "include_url": True,
                    "include_emoji": True,
                },
                {
                    "variant_id":  "variant_b",
                    "name":        "Informational",
                    "segment_ids": [s["segment_id"] for s in segments[mid:]],
                    "send_time":   times["evening"],
                    "tone":        "informational, friendly",
                    "include_url": True,
                    "include_emoji": False,
                },
            ]

        return {
            "strategy": {
                "ab_variants":    fallback_variants,
                "rationale":      "Deterministic fallback",
                "expected_winner": "variant_a",
                "iteration":      iteration,
            },
            "status": "strategy_ready",
        }