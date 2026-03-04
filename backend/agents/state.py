from typing import TypedDict, Optional, List

class CampaignState(TypedDict):
    campaign_id: str
    brief: str
    customers: List[dict]            # Full cohort
    segments: List[dict]             # Built by profiler
    strategy: dict                   # Built by strategist
    emails: List[dict]               # Built by content_gen
    external_campaign_ids: List[str] # Returned by send_campaign API
    metrics: dict                    # Computed by monitor
    iteration: int                   # Current loop count
    max_iterations: int              # Stop after this many
    rejection_reason: Optional[str]  # Set if human rejects
    optimization_notes: str          # Passed from optimizer to strategist
    status: str                      # Current pipeline status
