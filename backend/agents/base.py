"""
base.py — LLM factory, retry logic, SSE emitter, JSON cleaner.

Root fixes in this rewrite:
  1. invoke_with_retry strips lone surrogates at the SOURCE using re.sub
     so every downstream caller (content_gen, probe_executor, strategist,
     optimizer) is protected without needing per-caller patches.
  2. clean_llm_json strips surrogates first, then handles markdown fences,
     then bracket-matches — in the correct order.
"""

import os
import re
import asyncio
from dotenv import load_dotenv
from db.database import save_agent_log
from shared import sse_queues

load_dotenv()

# Lone Unicode surrogates (U+D800–U+DFFF) emitted by Llama 3.3-70B for emoji
# are illegal in UTF-8 and crash json.loads and SQLite writes.
_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")

def _strip_surrogates(text: str) -> str:
    return _SURROGATE_RE.sub("", text)


def get_llm(temperature: float = 0.7, force_gemini: bool = False):
    groq_key   = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    if groq_key and not force_gemini:
        from langchain_groq import ChatGroq
        return ChatGroq(
            model="llama-3.3-70b-versatile",
            groq_api_key=groq_key,
            temperature=temperature,
        )
    elif gemini_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            google_api_key=gemini_key,
            temperature=temperature,
        )
    else:
        raise ValueError("No LLM API key found. Set GROQ_API_KEY or GEMINI_API_KEY in .env")


async def invoke_with_retry(llm, prompt: str, max_retries: int = 3) -> str:
    """
    Calls LLM with automatic retry. Strips surrogates at the source —
    single choke point protecting all callers.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")

    for attempt in range(max_retries):
        try:
            response = llm.invoke(prompt)
            return _strip_surrogates(response.content)

        except Exception as e:
            error_str = str(e)
            is_rate_limit = (
                "429" in error_str
                or "quota" in error_str.lower()
                or "rate" in error_str.lower()
            )

            if is_rate_limit:
                if attempt == 1 and gemini_key:
                    print("[Rate limit] Switching to Gemini fallback...")
                    from langchain_google_genai import ChatGoogleGenerativeAI
                    llm = ChatGoogleGenerativeAI(
                        model="gemini-1.5-flash",
                        google_api_key=gemini_key,
                        temperature=0.7,
                    )
                else:
                    if attempt >= max_retries - 1:
                        break
                    wait = 15 * (attempt + 1)
                    print(f"[Rate limit] Attempt {attempt+1}/{max_retries}. Waiting {wait}s...")
                    await asyncio.sleep(wait)
            else:
                raise

    raise Exception(f"LLM failed after {max_retries} retries")


async def emit(campaign_id: str, agent: str, event_type: str,
               message: str, data: dict = {}):
    queue = sse_queues.get(campaign_id)
    if queue:
        await queue.put({
            "type":    event_type,
            "agent":   agent,
            "message": message,
            "data":    data,
        })
    save_agent_log(campaign_id, agent, f"[{event_type}] {message}")


def clean_llm_json(text: str) -> str:
    """
    Extract valid JSON from LLM response.
    Order: strip surrogates → strip whitespace → remove fences → bracket-match.
    """
    text = _strip_surrogates(text)
    text = text.strip()

    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith(("{", "[")):
                text = part
                break

    start = -1
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break

    if start == -1:
        return text

    open_char  = text[start]
    close_char = "}" if open_char == "{" else "]"
    depth = 0
    end   = -1

    for i in range(start, len(text)):
        if text[i] == open_char:
            depth += 1
        elif text[i] == close_char:
            depth -= 1
            if depth == 0:
                end = i
                break

    return text[start:end + 1] if end != -1 else text
