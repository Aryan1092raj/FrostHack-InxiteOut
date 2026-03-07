import os
import asyncio
from dotenv import load_dotenv
from db.database import save_agent_log
from shared import sse_queues

load_dotenv()

def get_llm(temperature: float = 0.7, force_gemini: bool = False):
    """
    Returns best available LLM.
    Tries Groq first (faster, higher limits), falls back to Gemini.
    """
    groq_key = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    if groq_key and not force_gemini:
        from langchain_groq import ChatGroq
        return ChatGroq(
            model="llama-3.3-70b-versatile",
            groq_api_key=groq_key,
            temperature=temperature
        )
    elif gemini_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            google_api_key=gemini_key,
            temperature=temperature
        )
    else:
        raise ValueError("No LLM API key found. Set GROQ_API_KEY or GEMINI_API_KEY in .env")


async def invoke_with_retry(llm, prompt: str, max_retries: int = 3) -> str:
    """
    Calls LLM with automatic retry on rate limit errors.
    Switches to Gemini after second Groq failure.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")

    for attempt in range(max_retries):
        try:
            response = llm.invoke(prompt)
            return response.content
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                # On second attempt switch to Gemini
                if attempt == 1 and gemini_key:
                    print(f"[Rate limit] Switching to Gemini fallback...")
                    from langchain_google_genai import ChatGoogleGenerativeAI
                    llm = ChatGoogleGenerativeAI(
                        model="gemini-1.5-flash",
                        google_api_key=gemini_key,
                        temperature=0.7
                    )
                else:
                    wait_time = 15 * (attempt + 1)
                    print(f"[Rate limit] Attempt {attempt+1}/{max_retries}. Waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
            else:
                raise e
    raise Exception(f"LLM failed after {max_retries} retries")


async def emit(campaign_id: str, agent: str, event_type: str, 
               message: str, data: dict = {}):
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
    """Strip markdown and extract valid JSON from LLM response."""
    text = text.strip()

    # Remove markdown code fences
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{") or part.startswith("["):
                text = part
                break

    # Find outermost { } or [ ]
    start = -1

    for i, ch in enumerate(text):
        if ch in "{[" and start == -1:
            start = i
            break

    if start == -1:
        return text

    # Match brackets properly
    open_char = text[start]
    close_char = "}" if open_char == "{" else "]"
    depth = 0
    end = -1

    for i in range(start, len(text)):
        if text[i] == open_char:
            depth += 1
        elif text[i] == close_char:
            depth -= 1
            if depth == 0:
                end = i
                break

    if end != -1:
        return text[start:end+1]

    return text
