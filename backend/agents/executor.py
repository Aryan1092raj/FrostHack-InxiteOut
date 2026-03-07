from agents.state import CampaignState
from agents.base import emit
from tools.campaignx_tools import tool_send_campaign
from db.database import update_campaign_status


async def executor_node(state: CampaignState) -> dict:
    campaign_id = state["campaign_id"]
    emails = state["emails"]

    await emit(campaign_id, "executor", "agent_thought",
               f"Executing campaign — sending {len(emails)} email variants via CampaignX API...")

    update_campaign_status(campaign_id, "running")

    external_campaign_ids = []

    for email in emails:
        variant = email["variant"]
        customer_ids = email["customer_ids"]
        subject = email["subject"]
        body = email["body"]
        send_time = email["send_time"]

        await emit(campaign_id, "executor", "action",
                   f"Sending {variant} to {len(customer_ids)} customers at {send_time}...")

        result = tool_send_campaign(
            subject=subject,
            body=body,
            list_customer_ids=customer_ids,
            send_time=send_time
        )

        if "error" in result:
            await emit(campaign_id, "executor", "agent_thought",
                       f"⚠️ Send issue for {variant}: {result['error']}")
        else:
            ext_id = result.get("campaign_id", "")
            external_campaign_ids.append(ext_id)
            await emit(campaign_id, "executor", "action",
                       f"✅ {variant} sent! External campaign ID: {ext_id}")

    await emit(campaign_id, "executor", "agent_thought",
               f"✅ All variants sent. {len(external_campaign_ids)} campaigns live. "
               f"Handing off to monitor...")

    return {
        "external_campaign_ids": external_campaign_ids,
        "status": "running"
    }
