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
  With 5000 customers, that's 4500 people getting an email we KNOW works.

RATE LIMIT MATH:
  5 probe sends + 5 probe reports = 10 API calls
  Remaining budget: ~90 calls for main iterations
  Probe pool: ~500 customers (10%)
  Main pool: ~4500 customers (90%)
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

PROBE_POOL_RATIO = 0.10     # 10% of cohort used for probing
MIN_PER_PROBE    = 50       # minimum per probe variant
MAX_PER_PROBE    = 200      # maximum per probe variant

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
        "dimension": "tone=trust-building | emoji=none | bold=heavy",
        "tone":      "trust-building",
        "subject_hint": "Credibility-first subject mentioning SuperBFSI's track record",
        "body_hint":    "Trust-building tone. No emojis. Bold key guarantees. Short punchy sentences. CTA at end.",
        "include_emoji": False,
    },
    {
        "probe_id":  "probe_E_special_offer",
        "dimension": "special_offer=female_senior | cta=multiple | personalisation=high",
        "tone":      "warm/personal",
        "subject_hint": "Highlight the exclusive 0.25% extra for senior women",
        "body_hint":    "Lead with the exclusive 0.25% bonus for female senior citizens. Warm tone. Personal. URL in first and last paragraph.",
        "include_emoji": True,
    },
]


async def _generate_probe_email(llm, tmpl: dict, brief: str) -> dict:
    """Generate a single probe email using LLM. Returns {subject, body}."""
    prompt = f"""You are writing a probe email for a CampaignX A/B test.

Campaign Brief: {brief}

Probe ID: {tmpl['probe_id']}
Signal Dimension: {tmpl['dimension']}
Tone: {tmpl['tone']}
Subject hint: {tmpl['subject_hint']}
Body hint: {tmpl['body_hint']}
Include emoji: {tmpl['include_emoji']}

STRICT RULES:
- Subject: plain English text only, max 200 chars, NO urgency/scarcity/FOMO
- Body: English text, emojis OK if include_emoji=True, MUST include URL: {XDEPOSIT_URL}
- Body max 5000 chars
- Preferred tones: trust-building, aspirational, informational, warm/personal
- BANNED tones: urgency, scarcity, FOMO

Return ONLY this JSON (no markdown):
{{
    "subject": "...",
    "body": "..."
}}"""

    content = await invoke_with_retry(llm, prompt)
    result = json.loads(clean_llm_json(content))
    subject = result.get("subject", f"Discover XDeposit — 1% More Returns")
    body = result.get("body", f"Dear valued customer,\n\nXDeposit offers 1% higher returns.\n\n👉 {XDEPOSIT_URL}\n\nBest regards,\nSuperBFSI Team")

    # Safety checks
    if len(subject) > 200:
        subject = subject[:197] + "..."
    if len(body) > 5000:
        body = body[:4990] + f"\n\n{XDEPOSIT_URL}"
    if XDEPOSIT_URL not in body:
        body = body + f"\n\n👉 {XDEPOSIT_URL}"

    return {"subject": subject, "body": body}


async def probe_executor_node(state: CampaignState) -> dict:
    """
    FIX: Wrapped entire function in top-level try/except.
    Any unhandled exception (LLM failure, JSON parse, API error) now
    falls back gracefully to probe_failed instead of crashing the pipeline.
    """
    campaign_id  = state["campaign_id"]
    customers    = state.get("customers", [])
    brief        = state["brief"]
    iteration    = state.get("iteration", 1)
    all_emailed  = set(state.get("all_emailed_customer_ids", []))

    # ── Default fallback state ─────────────────────────────────────────────────
    all_ids   = [c["customer_id"] for c in customers]
    available = [cid for cid in all_ids if cid not in all_emailed]
    # Reserve 10% for probe, 90% for main
    probe_pool_size = int(len(available) * PROBE_POOL_RATIO)
    main_pool_fallback = available[probe_pool_size:]

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
        await emit(campaign_id, "probe_executor", "agent_thought",
                   "🔬 PROBE → EXPLOIT ENGINE ACTIVATED")
        await emit(campaign_id, "probe_executor", "agent_thought",
                   "   Sending 5 micro-probes to 10% of cohort. "
                   "Thompson Sampling will pick winner for the remaining 90%.")

        # ── Build probe pool ───────────────────────────────────────────────────
        random.shuffle(available)

        probe_pool_size = max(
            len(PROBE_TEMPLATES) * MIN_PER_PROBE,
            int(len(available) * PROBE_POOL_RATIO)
        )
        probe_pool_size = min(probe_pool_size, int(len(available) * 0.15))

        probe_pool = available[:probe_pool_size]
        main_pool  = available[probe_pool_size:]

        per_probe = max(MIN_PER_PROBE, len(probe_pool) // len(PROBE_TEMPLATES))
        per_probe = min(per_probe, MAX_PER_PROBE)

        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"   📦 Probe pool: {len(probe_pool)} → "
                   f"{len(PROBE_TEMPLATES)} probes × ~{per_probe} each")
        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"   🎯 Main pool: {len(main_pool)} customers — gets the proven winner")

        # ── Future send time ───────────────────────────────────────────────────
        ist_now  = datetime.utcnow() + timedelta(hours=5, minutes=30)
        tomorrow = ist_now + timedelta(days=1)
        send_time = tomorrow.strftime("%d:%m:%y 09:00:00")

        # ── Generate probe emails ──────────────────────────────────────────────
        await emit(campaign_id, "probe_executor", "agent_thought",
                   "✍️  Generating 5 probe variants via LLM...")

        llm = get_llm(temperature=0.7)
        probe_configs = []

        for i, tmpl in enumerate(PROBE_TEMPLATES):
            chunk = probe_pool[i * per_probe : (i + 1) * per_probe]
            if not chunk:
                continue

            try:
                content = await _generate_probe_email(llm, tmpl, brief)
            except Exception as e:
                await emit(campaign_id, "probe_executor", "agent_thought",
                           f"   ⚠️  LLM failed for {tmpl['probe_id']}: {str(e)[:60]}. Using template fallback.")
                content = {
                    "subject": f"XDeposit: 1% Higher Returns for You",
                    "body":    f"Dear Customer,\n\nXDeposit offers 1% higher FD returns.\n\n👉 {XDEPOSIT_URL}\n\nBest,\nSuperBFSI"
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
                       f"   ✅ {tmpl['probe_id']}: '{content['subject'][:55]}...' → {len(chunk)} customers")

        # ── Send all probes ────────────────────────────────────────────────────
        await emit(campaign_id, "probe_executor", "action",
                   f"📤 Sending {len(probe_configs)} probe campaigns to CampaignX API...")

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

        sampler      = ThompsonSampler()
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
                           f"   ⚠️  Could not fetch report for {pid}: {report['error'][:60]}")
                sampler.update(pid, 0, len(probe["customer_ids"]))
                continue

            computed   = report.get("computed_metrics", {})
            click_rate = computed.get("click_rate", 0.0)
            open_rate  = computed.get("open_rate", 0.0)
            total      = computed.get("total_sent", len(probe["customer_ids"]))
            clicks     = computed.get("clicks", 0)

            sampler.update(pid, clicks, total)

            probe_results.append({
                "probe_id":    pid,
                "dimension":   probe["dimension"],
                "subject":     probe["subject"],
                "body":        probe["body"],
                "tone":        probe["tone"],
                "dna":         probe["dna"],
                "click_rate":  click_rate,
                "open_rate":   open_rate,
                "total":       total,
                "clicks":      clicks,
                "external_id": ext_id,
            })

            await emit(campaign_id, "probe_executor", "agent_thought",
                       f"   📈 {pid}: Open {open_rate:.1%} | Click {click_rate:.1%} | n={total}")

        # ── Thompson Sampling — pick winner ────────────────────────────────────
        rankings  = sampler.get_rankings()
        winner_id = sampler.get_winner(n_samples=2000)

        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"\n{sampler.summary_str()}")

        winner_probe = next(
            (p for p in probe_results if p["probe_id"] == winner_id),
            probe_results[0] if probe_results else None
        )

        if winner_probe:
            await emit(campaign_id, "probe_executor", "agent_thought",
                       f"\n🏆 THOMPSON WINNER: {winner_id}")
            await emit(campaign_id, "probe_executor", "agent_thought",
                       f"   Dimension: {winner_probe['dimension']}")
            await emit(campaign_id, "probe_executor", "agent_thought",
                       f"   Click Rate: {winner_probe['click_rate']:.1%} | Open: {winner_probe['open_rate']:.1%}")
            await emit(campaign_id, "probe_executor", "agent_thought",
                       f"   Subject: '{winner_probe['subject'][:80]}'")
            await emit(campaign_id, "probe_executor", "agent_thought",
                       f"   DNA: {winner_probe['dna']}")

            confident = sampler.is_confident_winner(threshold=0.75)
            await emit(campaign_id, "probe_executor", "agent_thought",
                       f"   Confidence: {'HIGH ✅' if confident else 'MODERATE ⚠️ (small probe sample)'}")

        # ── Email DNA Signal Extraction ────────────────────────────────────────
        signal_map  = compute_dna_signal(probe_results) if probe_results else {}
        winning_dna = get_winning_dna(signal_map)
        dna_rules   = dna_to_content_instructions(winning_dna)

        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"🧬 Winning DNA pattern: {winning_dna}")
        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"   DNA rules injected into content_gen for main campaign ✅")

        # ── Build Thompson winner state ────────────────────────────────────────
        thompson_winner = {}
        if winner_probe:
            thompson_winner = {
                "probe_id":          winner_id,
                "subject":           winner_probe["subject"],
                "body":              winner_probe["body"],
                "tone":              winner_probe["tone"],
                "dna":               winner_probe["dna"],
                "click_rate":        winner_probe["click_rate"],
                "open_rate":         winner_probe["open_rate"],
                "dimension":         winner_probe["dimension"],
                "thompson_rankings": rankings,
                "confidence_high":   sampler.is_confident_winner(),
            }

        new_all_emailed = list(all_emailed | set(probe_pool))

        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"\n✅ Probe phase complete. "
                   f"{len(main_pool)} customers queued for winning formula.")

        return {
            "probe_results":            probe_results,
            "thompson_winner":          thompson_winner,
            "email_dna_signal":         signal_map,
            "winning_dna":              winning_dna,
            "dna_content_rules":        dna_rules,
            "main_pool_customer_ids":   main_pool,
            "status":                   "probe_done",
            "all_emailed_customer_ids": new_all_emailed,
        }

    except Exception as e:
        # FIX: Top-level safety net — any unhandled exception falls back gracefully
        await emit(campaign_id, "probe_executor", "agent_thought",
                   f"⚠️  Probe phase encountered an error: {str(e)[:120]}. "
                   f"Falling back to standard A/B execution.")
        return _fallback(str(e))