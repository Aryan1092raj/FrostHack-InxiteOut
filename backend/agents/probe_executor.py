"""
🧠 Probe Executor — Innovation #1: Probe → Exploit via Thompson Sampling

WHAT IT DOES:
  Before the main campaign send, this node:
  1. Sends 5 radically different email formulas to ~10% of the cohort
  2. Fetches results IMMEDIATELY (gamified API — no waiting)
  3. Runs Thompson Sampling to identify the statistically best formula
  4. Extracts Email DNA signal (Innovation #2) from probe data
  5. Returns: the winning template + DNA constraints for the remaining 90%

WHY IT WINS:
  Standard A/B: 50% of your audience gets an untested, possibly weak email.
  Thompson + Probe: 10% pays the learning cost. 90% gets the proven winner.
  With 1000 customers, that's 900 people getting an email we KNOW works.

RATE LIMIT MATH (1000-customer cohort):
  5 probe sends + 5 probe reports = 10 API calls
  Remaining budget: ~90 calls/day for main iterations
  Probe pool: ~100 customers (10%)   ← was 500 when cohort was 5000
  Main pool:  ~900 customers (90%)   ← was 4500 when cohort was 5000
  Per probe:  ~20 customers          ← was ~100 when cohort was 5000
"""

import asyncio
import random
import json
from datetime import datetime, timedelta
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json, invoke_with_retry
from tools.campaignx_tools import tool_send_campaign, tool_get_report
from utils.thompson_sampling import ThompsonSampler
from utils.email_dna import extract_dna, compute_dna_signal, get_winning_dna, dna_to_content_instructions

XDEPOSIT_URL = "https://superbfsi.com/xdeposit/explore/"

# ── Pool size constants — tuned for 1000-customer final round cohort ──────────
PROBE_POOL_RATIO = 0.10   # 10% → 100 customers for probing
MIN_PER_PROBE    = 15     # minimum customers per probe variant (was 50 for 5000 cohort)
MAX_PER_PROBE    = 30     # maximum customers per probe variant (was 200 for 5000 cohort)
# With 1000 customers: 100 probe / 5 templates = 20 per probe ✓ (within 15–30 range)
# Main pool: 900 customers get the proven Thompson winner ✓

# ── 5 Probe Templates — each tests a DISTINCT, independent signal dimension ──
PROBE_TEMPLATES = [
    {
        "probe_id":  "probe_A_question",
        "dimension": "subject_opener=question | cta=multiple | emoji=sparse",
        "tone":      "warm/personal",
        "subject_hint": "Personal question about their FD returns, ends with ?",
        "body_hint":    "Open warm + personal. CTA URL in first 2 sentences AND end. 2-3 emojis. Medium length. Heavy 'you'/'your'.",
        "include_emoji": True,
    },
    {
        "probe_id":  "probe_B_number",
        "dimension": "subject_opener=number | cta=top | emoji=none",
        "tone":      "informational",
        "subject_hint": "Starts with '1%' or a specific number/rate",
        "body_hint":    "Lead with the 1% rate advantage. Data-driven. No emojis. Bold the key numbers. CTA in first paragraph. Professional.",
        "include_emoji": False,
    },
    {
        "probe_id":  "probe_C_aspirational",
        "dimension": "tone=aspirational | body=long | personalisation=high",
        "tone":      "aspirational",
        "subject_hint": "Future-looking, growth-focused statement about financial goals",
        "body_hint":    "Paint a picture of financial security. High personalisation (you/your 5+ times). Long body building the case. CTA as next step.",
        "include_emoji": True,
    },
    {
        "probe_id":  "probe_D_trust",
        "dimension": "tone=trust-building | social_proof=yes | cta=bottom",
        "tone":      "trust-building",
        "subject_hint": "Trust/credibility signal — SuperBFSI reputation or safety of deposits",
        "body_hint":    "Lead with SuperBFSI's credibility. Mention RBI-regulated, safe deposits. Social proof angle. CTA at end only.",
        "include_emoji": False,
    },
    {
        "probe_id":  "probe_E_special_offer",
        "dimension": "subject_opener=special_offer | senior_women_angle=yes | emoji=rich",
        "tone":      "warm/personal",
        "subject_hint": "Mention the special 0.25% extra for senior women or a personalised offer angle",
        "body_hint":    "Lead with the exclusive extra offer. Rich emojis (3-4). Short punchy sentences. Two CTAs — one early, one at end.",
        "include_emoji": True,
    },
]


async def _generate_probe_email(llm, tmpl: dict, brief: str) -> dict:
    """Ask the LLM to generate a single probe email from a template hint."""
    emoji_rule = (
        "Use 2-4 relevant emojis in the body." if tmpl["include_emoji"]
        else "Use ZERO emojis — clean text only."
    )
    prompt = f"""You are an expert email copywriter for a financial product campaign.

Campaign Brief: {brief}
Campaign URL (MUST appear in body): {XDEPOSIT_URL}

Generate ONE email for this probe variant:
  Probe ID:    {tmpl['probe_id']}
  Dimension:   {tmpl['dimension']}
  Tone:        {tmpl['tone']}
  Subject hint: {tmpl['subject_hint']}
  Body hint:    {tmpl['body_hint']}
  Emoji rule:   {emoji_rule}

HARD RULES:
- Subject: 35-80 chars, English only, no markdown
- Body: 80-250 words, must contain {XDEPOSIT_URL}
- BANNED tones: urgency, scarcity, FOMO, pressure — these are PENALISED by the API
- Allowed tones: trust-building, aspirational, informational, warm/personal

Return ONLY valid JSON:
{{"subject": "...", "body": "..."}}"""

    content = await invoke_with_retry(llm, prompt)
    return json.loads(clean_llm_json(content))


async def probe_executor_node(state: CampaignState) -> dict:
    """
    Probe → Exploit node.

    Updated for 1000-customer final-round cohort:
    - Probe pool: ~100 customers (10%)
    - Per probe:  ~20 customers (MIN_PER_PROBE=15, MAX_PER_PROBE=30)
    - Main pool:  ~900 customers (90%)

    Any unhandled exception falls back gracefully to probe_failed
    so the pipeline continues to executor without crashing.
    """
    campaign_id  = state["campaign_id"]
    customers    = state.get("customers", [])
    brief        = state["brief"]
    iteration    = state.get("iteration", 1)
    all_emailed  = set(state.get("all_emailed_customer_ids", []))

    # ── Default fallback ───────────────────────────────────────────────────────
    all_ids   = [c["customer_id"] for c in customers]
    available = [cid for cid in all_ids if cid not in all_emailed]

    # Safe fallback split: 10% probe, 90% main
    probe_pool_size_fallback = max(len(PROBE_TEMPLATES) * MIN_PER_PROBE,
                                   int(len(available) * PROBE_POOL_RATIO))
    probe_pool_size_fallback = min(probe_pool_size_fallback, len(available))
    main_pool_fallback = available[probe_pool_size_fallback:]

    def _fallback(reason: str) -> dict:
        return {
            "probe_results":            [],
            "thompson_winner":          {},
            "email_dna_signal":         {},
            "winning_dna":              {},
            "dna_content_rules":        "",
            "main_pool_customer_ids":   main_pool_fallback,
            "status":                   "probe_failed",
            "all_emailed_customer_ids": list(all_emailed),
        }

    # ── Skip on rescue iterations ──────────────────────────────────────────────
    if iteration > 1:
        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"⏭️  Iteration {iteration}: probe phase already done. "
                   f"Using learned DNA signal from iteration 1.")
        return {"status": "probe_skipped"}

    # ── Guard: need customers ──────────────────────────────────────────────────
    if not customers:
        await emit(campaign_id, "probe_executor", "agent_thought",
                   "⚠️  No customers loaded — skipping probe phase.")
        return _fallback("no customers")

    try:
        total_available = len(available)
        await emit(campaign_id, "probe_executor", "agent_thought",
                   "🔬 PROBE → EXPLOIT ENGINE ACTIVATED")
        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"   Cohort: {total_available} customers available. "
                   f"Sending 5 micro-probes to {PROBE_POOL_RATIO:.0%} (~{int(total_available * PROBE_POOL_RATIO)}). "
                   f"Thompson Sampling picks winner for the remaining {1 - PROBE_POOL_RATIO:.0%}.")

        # ── Build probe pool ───────────────────────────────────────────────────
        random.shuffle(available)

        # For 1000 customers: probe_pool_size = max(5×15, 10% of 1000) = max(75, 100) = 100
        # Capped at 15% = 150, so final = 100
        probe_pool_size = max(
            len(PROBE_TEMPLATES) * MIN_PER_PROBE,
            int(total_available * PROBE_POOL_RATIO)
        )
        probe_pool_size = min(probe_pool_size, int(total_available * 0.15))

        probe_pool = available[:probe_pool_size]
        main_pool  = available[probe_pool_size:]

        # per_probe: evenly divide probe pool across templates, clamp to [MIN, MAX]
        per_probe = max(MIN_PER_PROBE, len(probe_pool) // len(PROBE_TEMPLATES))
        per_probe = min(per_probe, MAX_PER_PROBE)

        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"   📦 Probe pool: {len(probe_pool)} customers → "
                   f"{len(PROBE_TEMPLATES)} probes × ~{per_probe} each")
        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"   🎯 Main pool: {len(main_pool)} customers — gets the proven winner")

        # ── Future send time ───────────────────────────────────────────────────
        ist_now   = datetime.utcnow() + timedelta(hours=5, minutes=30)
        send_dt   = ist_now + timedelta(minutes=15)
        send_time = send_dt.strftime("%d:%m:%y %H:%M:%S")

        # ── Generate probe emails ──────────────────────────────────────────────
        await emit(campaign_id, "probe_executor", "agent_thought",
                   "✍️  Generating 5 probe variants via LLM...")

        llm = get_llm(temperature=0.7)
        probe_configs = []

        for i, tmpl in enumerate(PROBE_TEMPLATES):
            chunk = probe_pool[i * per_probe : (i + 1) * per_probe]
            if not chunk:
                await emit(campaign_id, "probe_executor", "agent_thought",
                           f"   ⚠️  {tmpl['probe_id']}: empty chunk, skipping.")
                continue

            try:
                content = await _generate_probe_email(llm, tmpl, brief)
            except Exception as e:
                await emit(campaign_id, "probe_executor", "agent_thought",
                           f"   ⚠️  LLM failed for {tmpl['probe_id']}: {str(e)[:60]}. Using fallback.")
                content = {
                    "subject": "XDeposit: Earn 1% More on Your Fixed Deposit",
                    "body":    f"Dear Customer,\n\nXDeposit from SuperBFSI offers 1% higher FD returns "
                               f"than competitors.\n\n👉 {XDEPOSIT_URL}\n\nBest regards,\nSuperBFSI Team"
                }

            dna = extract_dna(content["subject"], content["body"], tmpl["tone"])

            probe_configs.append({
                "probe_id":     tmpl["probe_id"],
                "dimension":    tmpl["dimension"],
                "tone":         tmpl["tone"],
                "subject":      content["subject"],
                "body":         content["body"],
                "customer_ids": chunk,
                "send_time":    send_time,
                "dna":          dna,
            })

            await emit(campaign_id, "probe_executor", "agent_thought",
                       f"   ✅ {tmpl['probe_id']}: '{content['subject'][:55]}' → {len(chunk)} customers")

        if not probe_configs:
            return _fallback("no probe configs generated")

        # ── Send all probes ────────────────────────────────────────────────────
        await emit(campaign_id, "probe_executor", "action",
                   f"📤 Sending {len(probe_configs)} probe campaigns...")

        probe_ext_ids: dict[str, str] = {}

        for probe in probe_configs:
            result = tool_send_campaign(
                subject=probe["subject"],
                body=probe["body"],
                list_customer_ids=probe["customer_ids"],
                send_time=probe["send_time"],
            )

            if "error" in result:
                await emit(campaign_id, "probe_executor", "agent_thought",
                           f"   ⚠️  {probe['probe_id']} send failed: {result['error'][:80]}")
                continue

            ext_id = result.get("campaign_id", "")
            probe_ext_ids[probe["probe_id"]] = ext_id
            await emit(campaign_id, "probe_executor", "action",
                       f"   ✅ {probe['probe_id']} live → {ext_id[:8]}...")

        if not probe_ext_ids:
            await emit(campaign_id, "probe_executor", "agent_thought",
                       "❌ All probes failed to send. Falling back to standard A/B.")
            return _fallback("all probe sends failed")

        # ── Wait for gamified results ──────────────────────────────────────────
        await emit(campaign_id, "probe_executor", "agent_thought",
                   "⏳ Waiting 8s for gamified metrics to register...")
        await asyncio.sleep(8)

        # ── Fetch all probe reports ────────────────────────────────────────────
        await emit(campaign_id, "probe_executor", "action",
                   "📊 Fetching probe results and running Thompson Sampling...")

        sampler       = ThompsonSampler()
        probe_results: list[dict] = []

        for probe in probe_configs:
            pid    = probe["probe_id"]
            ext_id = probe_ext_ids.get(pid)
            if not ext_id:
                continue

            sampler.add_variant(pid)
            report = tool_get_report(ext_id)

            if "error" in report:
                await emit(campaign_id, "probe_executor", "agent_thought",
                           f"   ⚠️  Report fetch failed for {pid}: {report['error'][:60]}")
                sampler.update(pid, 0, len(probe["customer_ids"]))
                continue

            computed   = report.get("computed_metrics", {})
            click_rate = computed.get("click_rate", 0.0)
            open_rate  = computed.get("open_rate", 0.0)
            total      = computed.get("total_sent", len(probe["customer_ids"]))
            clicks     = int(round(click_rate * total))

            sampler.update(pid, clicks, total)

            probe_results.append({
                "probe_id":    pid,
                "dimension":   probe["dimension"],
                "subject":     probe["subject"],
                "body":        probe["body"],
                "tone":        probe["tone"],
                "click_rate":  click_rate,
                "open_rate":   open_rate,
                "total_sent":  total,
                "dna":         probe["dna"],
            })

            await emit(campaign_id, "probe_executor", "agent_thought",
                       f"   📊 {pid}: click={click_rate:.1%} open={open_rate:.1%} "
                       f"(n={total})")

        # ── Thompson Sampling — pick winner ───────────────────────────────────
        winner_id = sampler.sample_winner()
        winner    = next((p for p in probe_results if p["probe_id"] == winner_id), None)

        if not winner and probe_results:
            # fallback: best click rate
            winner = max(probe_results, key=lambda p: p["click_rate"])
            winner_id = winner["probe_id"]

        if winner:
            await emit(campaign_id, "probe_executor", "agent_thought",
                       f"🏆 Thompson winner: {winner_id} "
                       f"(click={winner['click_rate']:.1%}, "
                       f"dimension: {winner['dimension']})")
            await emit(campaign_id, "probe_executor", "agent_thought",
                       f"   Subject: '{winner['subject']}'")
        else:
            await emit(campaign_id, "probe_executor", "agent_thought",
                       "⚠️  No clear winner from Thompson Sampling. Using fallback.")
            return _fallback("no winner from thompson")

        # ── Email DNA extraction ───────────────────────────────────────────────
        email_dna_signal = compute_dna_signal(probe_results)
        winning_dna      = get_winning_dna(email_dna_signal)
        dna_rules        = dna_to_content_instructions(winning_dna)

        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"🧬 Email DNA extracted: {list(winning_dna.keys())}")
        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"📋 DNA content rules injected into content_gen prompt")

        # Track probed customer IDs as emailed
        probed_ids = [cid for p in probe_configs for cid in p["customer_ids"]]
        new_all_emailed = list(all_emailed) + probed_ids

        # Build permanent converter set from probe results (EC=Y → never re-target)
        probe_converted_ids: list[str] = []
        for probe in probe_configs:
            pid    = probe["probe_id"]
            ext_id = probe_ext_ids.get(pid)
            if not ext_id:
                continue
            # Re-use already-fetched report data via probe_results lookup
            rpt_result = next((r for r in probe_results if r["probe_id"] == pid), None)
            if rpt_result:
                # Fetch the raw row-level data to get per-customer EC
                raw_report = tool_get_report(ext_id)
                for row in raw_report.get("data", []):
                    if row.get("EC") == "Y":
                        cid = row.get("customer_id")
                        if cid:
                            probe_converted_ids.append(cid)

        if probe_converted_ids:
            await emit(campaign_id, "probe_executor", "agent_thought",
                       f"🔒 {len(probe_converted_ids)} probe converters (EC=Y) permanently excluded from future sends.")

        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"✅ Probe phase complete. "
                   f"{len(probed_ids)} probed + {len(main_pool)} reserved for main send.")

        return {
            "probe_results":              probe_results,
            "thompson_winner":            winner,
            "email_dna_signal":           email_dna_signal,
            "winning_dna":                winning_dna,
            "dna_content_rules":          dna_rules,
            "main_pool_customer_ids":     main_pool,
            "status":                     "probe_done",
            "all_emailed_customer_ids":   new_all_emailed,
            "all_converted_customer_ids": probe_converted_ids,
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"❌ Probe executor error: {str(e)[:120]}")
        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"   Traceback: {tb[:300]}")
        return _fallback(f"exception: {str(e)}")