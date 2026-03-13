"""
executor.py — Campaign sender.

Issues fixed in this rewrite:
  1. Thompson content override: variant_a now gets the actual winning probe
     subject and body, not just a flag that does nothing.
  2. 80/20 split: 80% of main pool → variant_a (proven winner),
     20% → variant_b (challenger). Previously was 50/50.
  3. Global dedup: customers already in all_emailed_customer_ids are removed
     before sending. Prevents double-sends across iterations.
  4. Per-variant dedup: if two variants somehow share customer IDs (shouldn't
     happen after content_gen fix, but belt-and-suspenders), second variant
     wins and first gets cleaned.
"""

from agents.state import CampaignState
from agents.base import emit
from tools.campaignx_tools import tool_send_campaign
from db.database import update_campaign_status


async def executor_node(state: CampaignState) -> dict:
    campaign_id     = state["campaign_id"]
    emails          = state["emails"]
    iteration       = state.get("iteration", 1)
    thompson_winner = state.get("thompson_winner", {})
    main_pool       = state.get("main_pool_customer_ids", [])
    dna_rules       = state.get("dna_content_rules", "")
    all_emailed     = set(state.get("all_emailed_customer_ids", []))

    await emit(campaign_id, "executor", "agent_thought",
               f"Executing campaign — iteration {iteration}...")

    update_campaign_status(campaign_id, "running")

    if not emails:
        await emit(campaign_id, "executor", "agent_thought",
                   "❌ No email variants in state. Content gen may have failed.")
        return {
            "external_campaign_ids":    [],
            "all_emailed_customer_ids": list(all_emailed),
            "status":                   "error",
        }

    # ── Thompson Probe→Exploit (iteration 1 only) ─────────────────────────────
    probe_succeeded = bool(thompson_winner and thompson_winner.get("subject")) and iteration == 1

    if probe_succeeded and main_pool:
        await emit(campaign_id, "executor", "agent_thought",
                   f"🧠 Probe-Exploit: distributing {len(main_pool)} customers. "
                   f"80% → proven winner (variant_a), 20% → challenger (variant_b).")

        # 80/20 split — winner gets the bulk
        winner_count     = int(len(main_pool) * 0.80)
        challenger_count = len(main_pool) - winner_count
        slices           = [main_pool[:winner_count], main_pool[winner_count:]]

        for i, email in enumerate(emails):
            if i < len(slices):
                email["customer_ids"] = slices[i]

            # FIX: Actually put the winning content into variant_a
            # Previously only set a flag; the actual subject/body were ignored
            if i == 0:
                email["subject"] = thompson_winner["subject"]
                email["body"]    = thompson_winner["body"]
                email["tone"]    = thompson_winner.get("tone", email.get("tone", ""))
                await emit(campaign_id, "executor", "agent_thought",
                           f"   variant_a → {winner_count} customers with WINNER: "
                           f"'{thompson_winner['subject'][:60]}'")
            else:
                await emit(campaign_id, "executor", "agent_thought",
                           f"   variant_b → {challenger_count} customers with challenger content")

    else:
        await emit(campaign_id, "executor", "agent_thought",
                   f"Standard execution: {len(emails)} variants with assigned customer lists.")

    # ── Send all variants ──────────────────────────────────────────────────────
    external_campaign_ids: list[str] = []
    new_emailed: set[str]            = set()

    for email in emails:
        variant      = email.get("variant", "variant_a")
        subject      = email.get("subject", "")
        body         = email.get("body", "")
        send_time    = email.get("send_time", "")
        raw_ids      = email.get("customer_ids", [])

        # Global dedup — remove anyone already emailed in a previous iteration
        customer_ids = [cid for cid in raw_ids if cid not in all_emailed and cid not in new_emailed]

        if not customer_ids:
            await emit(campaign_id, "executor", "agent_thought",
                       f"⚠️ {variant} has no customers after dedup — skipping.")
            continue

        if not subject or not body:
            await emit(campaign_id, "executor", "agent_thought",
                       f"⚠️ {variant} has empty subject or body — skipping.")
            continue

        await emit(campaign_id, "executor", "action",
                   f"Sending {variant} to {len(customer_ids)} customers at {send_time}...")

        result = tool_send_campaign(
            subject=subject,
            body=body,
            list_customer_ids=customer_ids,
            send_time=send_time,
        )

        if "error" in result:
            await emit(campaign_id, "executor", "agent_thought",
                       f"⚠️ Send failed for {variant}: {result['error']}")
        else:
            ext_id = result.get("campaign_id", "")
            if ext_id:
                external_campaign_ids.append(ext_id)
                new_emailed.update(customer_ids)
                # Track email→external_id mapping for monitor
                email["external_campaign_id"] = ext_id
                await emit(campaign_id, "executor", "action",
                           f"✅ {variant} sent. External ID: {ext_id}")

    if not external_campaign_ids:
        await emit(campaign_id, "executor", "agent_thought",
                   "❌ All sends failed. Check API key, send_time format, rate limit.")
        return {
            "external_campaign_ids":    [],
            "all_emailed_customer_ids": list(all_emailed),
            "status":                   "error",
        }

    all_emailed_updated = list(all_emailed | new_emailed)
    total_customers     = len(state.get("customers", []))

    await emit(campaign_id, "executor", "agent_thought",
               f"✅ {len(external_campaign_ids)} campaigns live. "
               f"Coverage: {len(all_emailed_updated)}/{total_customers} customers. "
               f"Handing to monitor...")

    return {
        "external_campaign_ids":    external_campaign_ids,
        "all_emailed_customer_ids": all_emailed_updated,
        "status":                   "running",
    }