import json
from agents.state import CampaignState
from agents.base import emit, get_llm, clean_llm_json, invoke_with_retry

XDEPOSIT_URL = "https://superbfsi.com/xdeposit/explore/"


async def content_gen_node(state: CampaignState) -> dict:
    campaign_id = state["campaign_id"]
    brief = state["brief"]
    segments = state["segments"]
    strategy = state["strategy"]
    rejection_reason = state.get("rejection_reason", "")
    iteration = state.get("iteration", 1)
    winning_variant_info: dict = state.get("winning_variant_info", {})

    await emit(campaign_id, "content_gen", "agent_thought",
               "Generating email content for each A/B variant...")

    llm = get_llm(temperature=0.8)

    # Build a map of segment_id → segment details
    segment_map = {s["segment_id"]: s for s in segments}

    emails = []

    for variant in strategy.get("ab_variants", []):
        variant_id = variant["variant_id"]
        tone = variant.get("tone", "professional")
        include_url = variant.get("include_url", True)
        include_emoji = variant.get("include_emoji", False)
        send_time = variant["send_time"]
        segment_ids = variant.get("segment_ids", [])
        direct_customer_ids: list = variant.get("direct_customer_ids", [])

        # Rescue mode: strategist already resolved exact customer IDs to target
        if direct_customer_ids:
            customer_ids = direct_customer_ids
            segment_descriptions = [
                f"Rescue pool ({len(direct_customer_ids)} non-clickers from last iteration)"
            ]
        else:
            # Standard mode: collect customer IDs from segment map
            customer_ids = []
            segment_descriptions = []
            for sid in segment_ids:
                seg = segment_map.get(sid, {})
                customer_ids.extend(seg.get("customer_ids", []))
                segment_descriptions.append(
                    f"{seg.get('name', sid)}: {seg.get('description', '')}"
                )

        if not customer_ids:
            await emit(campaign_id, "content_gen", "agent_thought",
                       f"⚠️ No customers for {variant_id}, skipping.")
            continue

        await emit(campaign_id, "content_gen", "agent_thought",
                   f"Writing {variant_id} email for {len(customer_ids)} customers "
                   f"(tone: {tone}, emoji: {include_emoji})...")

        prompt = f"""You are an expert email copywriter for SuperBFSI, an Indian BFSI company.

Campaign Brief: {brief}

Product: XDeposit Term Deposit
Key Facts:
- XDeposit gives 1 percentage point HIGHER returns than competitors
- EXTRA 0.25 percentage point for female senior citizens
- Call to action URL: {XDEPOSIT_URL}

Target Segments for this variant:
{chr(10).join(segment_descriptions)}

Variant Style:
- Tone: {tone}
- Include emojis: {include_emoji}
- Include CTA URL: {include_url}
- Rejection feedback to address: {rejection_reason or 'None'}

Email Rules (STRICT):
- Subject: Plain English text only, max 200 characters, NO URLs
- Body: English text only, emojis allowed, only URL allowed is {XDEPOSIT_URL}
- Use bold with **text**, italic with _text_, underline with <u>text</u>
- Body max 5000 characters
- Make it compelling to CLICK the link (click rate is most important)
- If targeting female senior citizens segment, prominently mention the 0.25% bonus

Return ONLY this JSON:
{{
    "subject": "Your email subject here",
    "body": "Your email body here with formatting"
}}"""

        try:
            raw = await invoke_with_retry(llm, prompt)
            content = json.loads(clean_llm_json(raw), strict=False)
            subject = content.get("subject", "")
            body = content.get("body", "")

            # Enforce URL rule
            if include_url and XDEPOSIT_URL not in body:
                body += f"\n\n👉 Explore XDeposit now: {XDEPOSIT_URL}"

            # Enforce length limits
            subject = subject[:200]
            body = body[:5000]

            await emit(campaign_id, "content_gen", "agent_thought",
                       f"✅ {variant_id} email written: '{subject[:60]}...'")

            emails.append({
                "variant": variant_id,
                "subject": subject,
                "body": body,
                "customer_ids": customer_ids,
                "send_time": send_time,
                "tone": tone,
                "segment_ids": segment_ids,
                "direct_customer_ids": direct_customer_ids
            })

        except Exception as e:
            await emit(campaign_id, "content_gen", "agent_thought",
                       f"⚠️ Content fallback for {variant_id}: {str(e)[:80]}")

            # Fallback template
            subject = f"XDeposit — Earn More with SuperBFSI's Best Term Deposit Rates"
            body = (
                f"Dear Valued Customer,\n\n"
                f"We're excited to introduce **XDeposit**, SuperBFSI's flagship term deposit "
                f"that gives you **1% higher returns** than our competitors.\n\n"
                f"🌟 Special offer for female senior citizens: Additional **0.25% bonus rate**!\n\n"
                f"Don't miss this opportunity to grow your savings.\n\n"
                f"👉 Explore XDeposit: {XDEPOSIT_URL}\n\n"
                f"Warm regards,\nSuperBFSI Team"
            )

            emails.append({
                "variant": variant_id,
                "subject": subject,
                "body": body,
                "customer_ids": customer_ids,
                "send_time": send_time,
                "tone": tone,
                "segment_ids": segment_ids,
                "direct_customer_ids": direct_customer_ids
            })

    await emit(campaign_id, "content_gen", "agent_thought",
               f"✅ Generated {len(emails)} email variants covering "
               f"{sum(len(e['customer_ids']) for e in emails)} customers total.")

    return {"emails": emails, "status": "content_ready"}
