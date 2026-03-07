import asyncio
import json
from typing import Dict, Any

# Dictionary mapping campaign_id to an asyncio.Queue for SSE events
campaign_queues: Dict[str, asyncio.Queue] = {}

def get_stream_queue(campaign_id: str) -> asyncio.Queue:
    if campaign_id not in campaign_queues:
        campaign_queues[campaign_id] = asyncio.Queue()
    return campaign_queues[campaign_id]

async def emit_event(campaign_id: str, event_type: str, agent: str, message: str, data: Dict[str, Any] = None):
    """Pushes a typed event to the SSE queue and also can be wired to save to DB."""
    if data is None:
        data = {}
        
    payload = {
        "type": event_type,
        "agent": agent,
        "message": message,
        "data": data
    }
    
    queue = get_stream_queue(campaign_id)
    await queue.put(json.dumps(payload))

async def yield_sse_events(campaign_id: str):
    """Generator for FastAPI StreamingResponse"""
    queue = get_stream_queue(campaign_id)
    try:
        while True:
            # Wait for next event
            message = await queue.get()
            # sse-starlette format: data: {...}\n\n
            yield f"data: {message}\n\n"
            
            # If done or error, we might optionally break the loop, 
            # but usually SSE stays open until client disconnects or we decide to close.
            payload = json.loads(message)
            if payload.get("type") in ["done", "error"]:
                break
    except asyncio.CancelledError:
        pass
    finally:
        # Cleanup if client disconnects
        if campaign_id in campaign_queues:
            # We don't strictly delete it here if other clients might connect, 
            # but for this scale we can leave it or clear it.
            pass
