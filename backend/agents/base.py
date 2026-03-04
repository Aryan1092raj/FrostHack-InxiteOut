import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from db.database import save_agent_log
from shared import sse_queues

load_dotenv()

def get_llm(temperature: float = 0.7):
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        google_api_key=os.getenv("GEMINI_API_KEY"),
        temperature=temperature
    )

async def emit(campaign_id: str, agent: str, event_type: str, message: str, data: dict = {}):
    """Push SSE event to frontend and save to agent logs."""
    queue = sse_queues.get(campaign_id)
    if queue:
        await queue.put({
            "type": event_type,
            "agent": agent,
            "message": message,
            "data": data
        })
    save_agent_log(campaign_id, agent, f"[{event_type}] {message}")

def clean_llm_json(text: str) -> str:
    """Strip markdown code fences from LLM JSON responses."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text.replace("json", "", 1)
    return text.strip()
