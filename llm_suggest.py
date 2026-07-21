"""
llm_suggest.py
Sends each distinct error group (not every individual occurrence) to Gemini
along with the user's issue description, and gets back a structured
root-cause + fix suggestion.

Requires: pip install google-generativeai
Requires env var: GEMINI_API_KEY

Get a free key (no credit card required) at https://aistudio.google.com/apikey
Free tier as of mid-2026: Gemini 2.5 Flash — 10 requests/min, 250 requests/day.
That's comfortably enough for analyzing a batch of error groups per incident.
"""

import json
import os
from typing import Optional

try:
    import google.generativeai as genai
except ImportError:
    genai = None

MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """You are a senior SAP Hybris / Java engineer helping debug production issues \
from log analysis. You will be given: (1) a description of the issue a user is experiencing, \
and (2) one distinct error/exception found in the logs during the relevant time window, \
including its stack trace and how many times it occurred.

Respond with ONLY a JSON object (no markdown fences, no preamble) with these fields:
{
  "relevance": "high" | "medium" | "low",   // how likely this error explains the described issue
  "root_cause": "...",                       // concise explanation of what's actually going wrong
  "suggested_fix": "...",                    // concrete, actionable fix or investigation step
  "hybris_context": "..."                    // optional: relevant Hybris module/config area, or ""
}"""


def build_user_prompt(issue_description: str, group) -> str:
    sample = group.sample_entry
    stack = sample.raw_text
    if len(stack) > 4000:
        stack = stack[:4000] + "\n... (truncated)"

    return f"""Issue described by the user:
{issue_description}

Error found in logs:
- Exception: {group.exception_class}
- Message: {group.message}
- Occurrences in time window: {group.count}
- First seen: {group.first_seen}
- Last seen: {group.last_seen}

Full stack trace (representative sample):
{stack}
"""


def suggest_fix(issue_description: str, group, api_key: Optional[str] = None) -> dict:
    """Returns a dict with relevance/root_cause/suggested_fix/hybris_context.
    Falls back to a placeholder if no API key / package is available, so the
    rest of the pipeline (report generation) still works end-to-end."""
    key = api_key or os.environ.get("GEMINI_API_KEY")

    if not key or genai is None:
        return {
            "relevance": "unknown",
            "root_cause": "(LLM suggestion unavailable — set GEMINI_API_KEY to enable this.)",
            "suggested_fix": "",
            "hybris_context": "",
        }

    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel(MODEL, system_instruction=SYSTEM_PROMPT)
        response = model.generate_content(
            build_user_prompt(issue_description, group),
            generation_config={"response_mime_type": "application/json"},
        )
        text = response.text.strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(text)
    except Exception as exc:  # noqa: BLE001 - surface any failure into the report itself
        return {
            "relevance": "unknown",
            "root_cause": f"(LLM call failed: {exc})",
            "suggested_fix": "",
            "hybris_context": "",
        }