import asyncio

# One SSE queue per campaign — agents push events, SSE endpoint reads them
sse_queues: dict[str, asyncio.Queue] = {}

# One event per campaign — approval node waits, /approve or /reject sets it
approval_events: dict[str, asyncio.Event] = {}

# Stores the human's decision per campaign
approval_decisions: dict[str, dict] = {}
