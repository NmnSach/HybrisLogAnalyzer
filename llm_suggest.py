"""
llm_suggest.py

Uses Groq to analyze clustered Hybris errors and suggest fixes.

Requires:
    pip install groq

Env:
    GROQ_API_KEY=gsk_xxxxx
"""

import json
import os
from typing import Optional

try:
    from groq import Groq
except ImportError:
    Groq = None


MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """
You are a Principal SAP Commerce Cloud (Hybris) Production Support Engineer.

Expertise:
- SAP Commerce Cloud
- Spring Framework
- Tomcat
- Solr
- FlexibleSearch
- CronJobs
- Business Process Engine
- OCC APIs
- Integration APIs
- ImpEx
- Azure Commerce Cloud deployments

Analyze the supplied error and determine:

1. Whether it explains the user's issue.
2. Probable root cause.
3. Most likely SAP Commerce component involved.
4. Exact troubleshooting actions.

Return ONLY JSON:

{
  "relevance":"high|medium|low",
  "root_cause":"...",
  "suggested_fix":"...",
  "hybris_context":"..."
}
"""

def build_user_prompt(issue_description: str, group) -> str:
    sample = group.sample_entry

    stack = sample.raw_text
    if len(stack) > 4000:
        stack = stack[:4000] + "\n...(truncated)"

    return f"""
Issue reported:

{issue_description}

Detected log error:

Exception: {group.exception_class}

Message:
{group.message}

Occurrences:
{group.count}

First seen:
{group.first_seen}

Last seen:
{group.last_seen}

Representative stack trace:

{stack}
"""


def suggest_fix(
    issue_description: str,
    group,
    api_key: Optional[str] = None,
):
    """
    Returns:
    {
      relevance,
      root_cause,
      suggested_fix,
      hybris_context
    }
    """

    key = api_key or os.getenv("GROQ_API_KEY")

    if not key or Groq is None:
        return {
            "relevance": "unknown",
            "root_cause": "LLM suggestion unavailable. Set GROQ_API_KEY.",
            "suggested_fix": "",
            "hybris_context": "",
        }

    try:
        client = Groq(api_key=key)

        response = client.chat.completions.create(
            model=MODEL,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": build_user_prompt(
                        issue_description,
                        group,
                    ),
                },
            ],
        )

        text = response.choices[0].message.content.strip()

        return json.loads(text)

    except Exception as exc:
        return {
            "relevance": "unknown",
            "root_cause": f"(LLM call failed: {exc})",
            "suggested_fix": "",
            "hybris_context": "",
        }
