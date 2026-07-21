"""
report_generator.py
Builds a standalone, self-contained HTML report from clustered error groups
and their LLM-suggested fixes. No external CSS/JS dependencies, so the file
can be emailed / archived / opened anywhere.
"""

import html
from datetime import datetime
from typing import List


RELEVANCE_COLOR = {
    "high": "#c0392b",
    "medium": "#d68910",
    "low": "#7f8c8d",
    "unknown": "#95a5a6",
}

CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       background: #f4f5f7; margin: 0; padding: 32px; color: #1f2430; }
.container { max-width: 980px; margin: 0 auto; }
h1 { font-size: 22px; margin-bottom: 4px; }
.meta { color: #667085; font-size: 13px; margin-bottom: 28px; }
.card { background: #fff; border: 1px solid #e4e7ec; border-radius: 10px;
        padding: 20px 24px; margin-bottom: 18px; box-shadow: 0 1px 2px rgba(16,24,40,0.04); }
.card-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.exc-class { font-family: SFMono-Regular, Consolas, monospace; font-size: 14px; font-weight: 600; color: #1f2430; word-break: break-all; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px;
         font-weight: 600; color: #fff; }
.count-badge { background: #344054; color: #fff; padding: 2px 10px; border-radius: 999px; font-size: 12px; }
.message { color: #475467; margin: 10px 0; font-size: 14px; }
.timerange { color: #98a2b3; font-size: 12px; margin-bottom: 10px; }
details { margin-top: 10px; }
summary { cursor: pointer; color: #2970ff; font-size: 13px; font-weight: 500; }
pre { background: #101828; color: #d0d5dd; padding: 14px; border-radius: 8px; overflow-x: auto;
      font-size: 12px; line-height: 1.5; margin-top: 8px; }
.fix-box { background: #f0f9f0; border: 1px solid #d1e7d1; border-radius: 8px; padding: 12px 16px; margin-top: 12px; }
.fix-box h4 { margin: 0 0 6px 0; font-size: 13px; color: #1a7a1a; }
.fix-box p { margin: 4px 0; font-size: 13px; color: #2d3a2d; }
.empty { text-align: center; color: #667085; padding: 60px 0; }
"""


def _relevance_badge(relevance: str) -> str:
    color = RELEVANCE_COLOR.get(relevance, RELEVANCE_COLOR["unknown"])
    return f'<span class="badge" style="background:{color}">{html.escape(relevance)} relevance</span>'


def generate_html_report(
    issue_description: str,
    window_start: datetime,
    window_end: datetime,
    groups: List,
    suggestions: dict,
    source_label: str = "",
) -> str:
    """suggestions: dict mapping group.fingerprint -> suggestion dict from llm_suggest.suggest_fix"""

    cards = []
    for g in groups:
        sug = suggestions.get(g.fingerprint, {})
        fix_html = ""
        if sug.get("root_cause") or sug.get("suggested_fix"):
            fix_html = f"""
            <div class="fix-box">
                <h4>Suggested diagnosis & fix</h4>
                <p><strong>Root cause:</strong> {html.escape(sug.get('root_cause',''))}</p>
                {"<p><strong>Fix:</strong> " + html.escape(sug.get('suggested_fix','')) + "</p>" if sug.get('suggested_fix') else ""}
                {"<p><strong>Hybris context:</strong> " + html.escape(sug.get('hybris_context','')) + "</p>" if sug.get('hybris_context') else ""}
            </div>"""

        cards.append(f"""
        <div class="card">
            <div class="card-header">
                <div class="exc-class">{html.escape(g.exception_class)}</div>
                <div>
                    {_relevance_badge(sug.get('relevance','unknown'))}
                    <span class="count-badge">{g.count} occurrence{'s' if g.count != 1 else ''}</span>
                </div>
            </div>
            <div class="message">{html.escape(g.message[:400])}</div>
            <div class="timerange">First seen: {g.first_seen} &nbsp;•&nbsp; Last seen: {g.last_seen}</div>
            {fix_html}
            <details>
                <summary>View sample stack trace</summary>
                <pre>{html.escape(g.sample_entry.raw_text)}</pre>
            </details>
        </div>
        """)

    body = "\n".join(cards) if cards else '<div class="empty">No errors found in the specified time window.</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Hybris Log Analysis Report</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
    <h1>Hybris Log Analysis Report</h1>
    <div class="meta">
        Issue: {html.escape(issue_description)}<br>
        Window: {window_start} &rarr; {window_end}<br>
        {"Source: " + html.escape(source_label) + "<br>" if source_label else ""}
        Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &nbsp;•&nbsp; {len(groups)} distinct error group(s)
    </div>
    {body}
</div>
</body>
</html>"""
