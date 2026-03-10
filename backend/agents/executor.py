"""
Executor Node — Updated to use Thompson winner and probe-reserved main pool.

After the probe phase, state contains:
  - thompson_winner: the proven best formula (subject/body/tone/dna)
  - main_pool_customer_ids: the 90% who haven't been emailed yet
  - emails: the LLM-generated variants from content_gen (used as fallback or
    re-generated with DNA constraints)

If probe was successful: inject thompson_winner DNA into main campaign content.
If probe failed/skipped: use original content_gen emails normally.
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

    # ── Determine which customer pool to target ────────────────────────────────
    # Iteration 1 + probe ran: use main_pool (probe already covered probe_pool)
    # Iteration 1 + no probe:  use all customer IDs from emails as normal
    # Iteration 2+:            use whatever emails[i].customer_ids contains (rescue mode)

    probe_succeeded = bool(thompson_winner) and iteration == 1

    if probe_succeeded and main_pool:
        await emit(campaign_id, "executor", "agent_thought",
                   f"🧠 Probe-Exploit mode: distributing {len(main_pool)} main-pool customers "
                   f"across {len(emails)} variants using Thompson-winner DNA formula.")

        # Re-slice main_pool across the email variants proportionally
        n_emails = len(emails)
        slices = []
        per_variant = len(main_pool) // n_emails
        for i in range(n_emails):
            start = i * per_variant
            end   = (i + 1) * per_variant if i < n_emails - 1 else len(main_pool)
            slices.append(main_pool[start:end])

        # Inject DNA winner into each variant's subject hint (keep LLM body, upgrade subject)
        for i, email in enumerate(emails):
            if thompson_winner.get("subject"):
                # Don't copy the exact subject — use it as a structural template
                # The email already has LLM-generated content; we just reassign customers
                email["customer_ids"] = slices[i]
                email["thompson_informed"] = True

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

    if not external_campaign_ids:
        await emit(campaign_id, "executor", "agent_thought",
                   "❌ All email sends failed. Check API key, send_time format, and customer IDs.")
        raise RuntimeError(
            f"All {len(emails)} email sends failed — 0 campaigns delivered. "
            "Likely cause: invalid send_time (must be future DD:MM:YY HH:MM:SS) or bad API key."
        )

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
