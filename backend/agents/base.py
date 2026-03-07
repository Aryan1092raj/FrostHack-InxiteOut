import os
import asyncio
from dotenv import load_dotenv
from db.database import save_agent_log
from shared import sse_queues

load_dotenv()

def get_llm(temperature: float = 0.7):
    """
    Returns best available LLM.
    Tries Groq first (faster, higher limits), falls back to Gemini.
    """
    groq_key = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    if groq_key:
        try:
            from groq import Groq

            class GroqLLM:
                """Wrapper around raw Groq SDK to match LangChain interface."""
                def __init__(self, api_key, model, temperature):
                    self.client = Groq(api_key=api_key)
                    self.model = model
                    self.temperature = temperature

                def invoke(self, prompt):
                    completion = self.client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=self.temperature
                    )
                    return completion.choices[0].message  # has .content

            return GroqLLM(
                api_key=groq_key,
                model="llama-3.3-70b-versatile",
                temperature=temperature
            )
        except ImportError:
            print("[Warning] groq package not installed. Falling back to Gemini.")
    
    if gemini_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",   # explicitly 1.5 not 2.0
            google_api_key=gemini_key,
            temperature=temperature
        )
    else:
        raise ValueError("No LLM API key found. Set GROQ_API_KEY or GEMINI_API_KEY in .env")


async def invoke_with_retry(llm, prompt: str, max_retries: int = 3) -> str:
    """
    Calls LLM with automatic retry on rate limit errors.
    Waits 40 seconds between retries.
    """
    for attempt in range(max_retries):
        try:
            response = llm.invoke(prompt)
            return response.content
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                wait_time = 40 * (attempt + 1)  # 40s, 80s, 120s
                print(f"[Rate limit] Attempt {attempt+1}/{max_retries}. Waiting {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
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
    """Strip markdown code fences and fix control characters in LLM JSON responses."""
    import re
    text = text.strip()

    # Handle ```json ... ``` blocks
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{") or part.startswith("["):
                text = part
                break

    # Find first { or [ and last } or ]
    start = min(
        text.find("{") if "{" in text else len(text),
        text.find("[") if "[" in text else len(text)
    )
    end = max(text.rfind("}"), text.rfind("]"))

    if 0 <= start < end:
        text = text[start:end+1]

    # Fix control characters inside JSON string values
    # Replace literal newlines/tabs/carriage returns with escaped versions
    def fix_string(match):
        s = match.group(0)
        s = s.replace('\n', '\\n')
        s = s.replace('\r', '\\r')
        s = s.replace('\t', '\\t')
        return s

    # Match JSON string values (between double quotes, handling escaped quotes)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', fix_string, text, flags=re.DOTALL)

    return text
