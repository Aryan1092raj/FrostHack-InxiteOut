"""
Executor Node — Updated to use Thompson winner and probe-reserved main pool.

FIX: Replaced `raise RuntimeError` with graceful error state return so that
a failed send does NOT crash the entire pipeline. The orchestrator will set
status to "error" on exception, but now we return cleanly with useful info.
"""

from agents.state import CampaignState
from agents.base import emit
from tools.campaignx_tools import tool_send_campaign
from db.database import update_campaign_status


async def executor_node(state: CampaignState) -> dict:
    campaign_id      = state["campaign_id"]
    emails           = state["emails"]
    iteration        = state.get("iteration", 1)
    thompson_winner  = state.get("thompson_winner", {})
    main_pool        = state.get("main_pool_customer_ids", [])
    dna_rules        = state.get("dna_content_rules", "")
    all_emailed      = set(state.get("all_emailed_customer_ids", []))

    await emit(campaign_id, "executor", "agent_thought",
               f"Executing campaign — iteration {iteration}...")

    update_campaign_status(campaign_id, "running")

    # ── Guard: no emails built ─────────────────────────────────────────────────
    if not emails:
        await emit(campaign_id, "executor", "agent_thought",
                   "❌ No email variants found in state. Content gen may have failed.")
        # Return error state gracefully — don't raise
        return {
            "external_campaign_ids":    [],
            "all_emailed_customer_ids": list(all_emailed),
            "status":                   "error",
        }

    # ── Determine which customer pool to target ────────────────────────────────
    probe_succeeded = bool(thompson_winner) and iteration == 1

    if probe_succeeded and main_pool:
        await emit(campaign_id, "executor", "agent_thought",
                   f"🧠 Probe-Exploit mode: distributing {len(main_pool)} main-pool customers "
                   f"across {len(emails)} variants using Thompson-winner DNA formula.")

        n_emails   = len(emails)
        per_variant = len(main_pool) // n_emails
        slices     = []
        for i in range(n_emails):
            start = i * per_variant
            end   = (i + 1) * per_variant if i < n_emails - 1 else len(main_pool)
            slices.append(main_pool[start:end])

        for i, email in enumerate(emails):
            if thompson_winner.get("subject"):
                email["customer_ids"]       = slices[i]
                email["thompson_informed"]  = True

        await emit(campaign_id, "executor", "agent_thought",
                   f"   Thompson winner informed {len(emails)} variants. "
                   f"DNA rules active: {bool(dna_rules)}")
    else:
        await emit(campaign_id, "executor", "agent_thought",
                   f"Standard execution: {len(emails)} variants with original customer assignments.")

    # ── Send all variants ──────────────────────────────────────────────────────
    external_campaign_ids = []
    new_emailed: set[str] = set()

    for email in emails:
        variant      = email["variant"]
        customer_ids = email.get("customer_ids", [])
        subject      = email["subject"]
        body         = email["body"]
        send_time    = email["send_time"]

        if not customer_ids:
            await emit(campaign_id, "executor", "agent_thought",
                       f"⚠️  {variant} has no customer IDs — skipping.")
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
                       f"⚠️  Send issue for {variant}: {result['error']}")
        else:
            ext_id = result.get("campaign_id", "")
            external_campaign_ids.append(ext_id)
            new_emailed.update(customer_ids)
            await emit(campaign_id, "executor", "action",
                       f"✅ {variant} sent! External campaign ID: {ext_id}")

    # FIX: Instead of raise RuntimeError (which crashes pipeline), return gracefully
    if not external_campaign_ids:
        await emit(campaign_id, "executor", "agent_thought",
                   "❌ All email sends failed. Check API key, send_time format, and customer IDs. "
                   "Likely cause: invalid/expired API key, rate limit hit, or send_time in the past.")
        # Return partial state so monitor/optimizer can still handle things
        return {
            "external_campaign_ids":    [],
            "all_emailed_customer_ids": list(all_emailed),
            "status":                   "error",
        }

    all_emailed_updated = list(all_emailed | new_emailed)
    coverage = len(all_emailed_updated)
    total    = len(state.get("customers", []))

    await emit(campaign_id, "executor", "agent_thought",
               f"✅ All variants sent. {len(external_campaign_ids)} campaigns live. "
               f"Cohort coverage: {coverage}/{total} customers emailed. "
               f"Handing off to monitor...")

    return {
        "external_campaign_ids":    external_campaign_ids,
        "all_emailed_customer_ids": all_emailed_updated,
        "status":                   "running",
    }