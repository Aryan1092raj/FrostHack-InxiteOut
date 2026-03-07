from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


# ─── Campaign Schemas ─────────────────────────────────────────────────────────

class Strategy(BaseModel):
    segments: List[List[str]]           # [[CUST001, CUST002], [CUST003]]
    send_times: List[str]               # ["03:03:26 09:00:00", ...]
    ab_variants: List[str]              # ["variant_a", "variant_b"]
    rationale: Optional[str] = None     # Why this strategy was chosen


class EmailVariant(BaseModel):
    variant: str                        # "variant_a"
    subject: str
    body: str
    customer_ids: List[str]
    send_time: str


class Metrics(BaseModel):
    open_rate: float = 0.0
    click_rate: float = 0.0
    total_sent: int = 0
    opens: int = 0
    clicks: int = 0


class Campaign(BaseModel):
    id: str
    brief: str
    status: str                         # planning|awaiting_approval|running|monitoring|optimizing|done|stopped
    strategy: Optional[Strategy] = None
    emails: Optional[List[EmailVariant]] = None
    metrics: Optional[Metrics] = None
    iteration: int = 1
    max_iterations: int = 3
    created_at: str
    updated_at: str


# ─── Request Bodies ───────────────────────────────────────────────────────────

class StartCampaignRequest(BaseModel):
    brief: str


class RejectCampaignRequest(BaseModel):
    reason: Optional[str] = "No reason provided"


class SignupRequest(BaseModel):
    team_name: str
    team_email: str


# ─── SSE Event Schema ─────────────────────────────────────────────────────────

class SSEEvent(BaseModel):
    type: str       # agent_thought|action|approval_needed|metric_update|done|error
    agent: str      # profiler|strategist|content_gen|executor|monitor|optimizer|orchestrator
    message: str
    data: Optional[Any] = None


# ─── Response Schemas ─────────────────────────────────────────────────────────

class CampaignListResponse(BaseModel):
    campaigns: List[Campaign]
    total: int


class ReportResponse(BaseModel):
    campaign_id: str
    open_rate: float
    click_rate: float
    total_sent: int
    opens: int
    clicks: int
    fetched_at: str
    raw_report: Optional[Any] = None


class RateLimitStatus(BaseModel):
    limits: dict
    max_per_day: int = 100