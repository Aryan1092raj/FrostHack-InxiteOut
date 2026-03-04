from sqlalchemy.orm import Session
from datetime import datetime
from . import database, schemas
import uuid

def create_campaign(db: Session, brief: str) -> database.CampaignDB:
    campaign_id = str(uuid.uuid4())
    db_campaign = database.CampaignDB(
        id=campaign_id,
        brief=brief,
        status="planning"
    )
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    return db_campaign

def get_campaign(db: Session, campaign_id: str) -> database.CampaignDB:
    return db.query(database.CampaignDB).filter(database.CampaignDB.id == campaign_id).first()

def get_campaigns(db: Session):
    return db.query(database.CampaignDB).order_by(database.CampaignDB.created_at.desc()).all()

def update_campaign_status(db: Session, campaign_id: str, status: str):
    campaign = get_campaign(db, campaign_id)
    if campaign:
        campaign.status = status
        db.commit()
        db.refresh(campaign)
    return campaign

def add_agent_log(db: Session, campaign_id: str, agent: str, thought: str):
    db_log = database.AgentLogDB(
        campaign_id=campaign_id,
        agent=agent,
        thought=thought
    )
    db.add(db_log)
    db.commit()
    return db_log

def get_agent_logs(db: Session, campaign_id: str):
    return db.query(database.AgentLogDB).filter(database.AgentLogDB.campaign_id == campaign_id).order_by(database.AgentLogDB.timestamp.asc()).all()

def check_rate_limit(db: Session, endpoint: str) -> bool:
    """Returns True if within limit, False if exceeded."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    tracker = db.query(database.RateLimitTrackerDB).filter(
        database.RateLimitTrackerDB.endpoint == endpoint,
        database.RateLimitTrackerDB.date == today
    ).first()

    if tracker and tracker.call_count >= 100:
        return False
    return True

def increment_rate_limit(db: Session, endpoint: str):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    tracker = db.query(database.RateLimitTrackerDB).filter(
        database.RateLimitTrackerDB.endpoint == endpoint,
        database.RateLimitTrackerDB.date == today
    ).first()

    if not tracker:
        tracker = database.RateLimitTrackerDB(endpoint=endpoint, date=today, call_count=1)
        db.add(tracker)
    else:
        tracker.call_count += 1
    db.commit()

def get_cached_cohort(db: Session):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    tracker = db.query(database.RateLimitTrackerDB).filter(
        database.RateLimitTrackerDB.endpoint == "/api/cohort",
        database.RateLimitTrackerDB.date == today
    ).first()
    if tracker and tracker.cached_response:
        return tracker.cached_response
    return None

def set_cached_cohort(db: Session, data: dict):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    tracker = db.query(database.RateLimitTrackerDB).filter(
        database.RateLimitTrackerDB.endpoint == "/api/cohort",
        database.RateLimitTrackerDB.date == today
    ).first()
    
    if not tracker:
        tracker = database.RateLimitTrackerDB(endpoint="/api/cohort", date=today, call_count=1, cached_response=data)
        db.add(tracker)
    else:
        tracker.cached_response = data
        tracker.call_count += 1
    db.commit()
