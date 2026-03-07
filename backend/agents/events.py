import asyncio
from typing import Dict

# Dictionary mapping campaign_id to an asyncio.Event
# This bridges the gap between the FastAPI REST requests and the background LangGraph execution thread.
campaign_approval_events: Dict[str, asyncio.Event] = {}

def get_approval_event(campaign_id: str) -> asyncio.Event:
    """Gets or creates the approval event for a specific campaign"""
    if campaign_id not in campaign_approval_events:
        campaign_approval_events[campaign_id] = asyncio.Event()
    return campaign_approval_events[campaign_id]

def set_approval_event(campaign_id: str):
    """Triggers the approval event, allowing the graph to resume execution"""
    if campaign_id in campaign_approval_events:
        campaign_approval_events[campaign_id].set()

def clear_approval_event(campaign_id: str):
    """Resets the approval event so it can pause again on the next iteration"""
    if campaign_id in campaign_approval_events:
        campaign_approval_events[campaign_id].clear()
