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
    "high": ("#b91c1c", "rgba(185, 28, 28, 0.10)", "rgba(185, 28, 28, 0.18)"),
    "medium": ("#a16207", "rgba(161, 98, 7, 0.12)", "rgba(161, 98, 7, 0.20)"),
    "low": ("#4b5563", "rgba(75, 85, 99, 0.10)", "rgba(75, 85, 99, 0.16)"),
    "unknown": ("#475569", "rgba(71, 85, 105, 0.10)", "rgba(71, 85, 105, 0.16)"),
}

CSS = """
:root {
  --bg: #f3f5f8;
  --surface: rgba(255, 255, 255, 0.8);
  --surface-solid: #ffffff;
  --surface-soft: #f7f8fb;
  --line: rgba(15, 23, 42, 0.08);
  --line-strong: rgba(15, 23, 42, 0.14);
  --text: #111827;
  --muted: #677083;
  --muted-soft: #97a0af;
  --accent: #15171c;
  --accent-soft: #eef2f6;
  --shadow: 0 24px 80px rgba(15, 23, 42, 0.08);
  --radius-xl: 30px;
  --radius-lg: 24px;
  --radius-md: 18px;
  --radius-sm: 14px;
  --ease: cubic-bezier(0.22, 1, 0.36, 1);
}

* { box-sizing: border-box; }
html, body { min-height: 100%; }

body {
  margin: 0;
  font-family: "Geist", "Segoe UI", sans-serif;
  color: var(--text);
  background:
    radial-gradient(circle at top left, rgba(20, 184, 166, 0.08), transparent 22%),
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.10), transparent 18%),
    linear-gradient(180deg, #fbfcfd 0%, #f3f5f8 100%);
  opacity: 0;
  animation: pageFadeIn 720ms var(--ease) forwards;
}

.shell {
  position: relative;
  padding: 28px 20px 56px;
  overflow: hidden;
}

.shell::before,
.shell::after {
  content: "";
  position: absolute;
  border-radius: 999px;
  filter: blur(18px);
  opacity: 0.72;
  pointer-events: none;
}

.shell::before {
  width: 320px;
  height: 320px;
  top: -100px;
  right: -90px;
  background: rgba(148, 163, 184, 0.16);
}

.shell::after {
  width: 420px;
  height: 420px;
  left: -180px;
  bottom: -160px;
  background: rgba(99, 102, 241, 0.10);
}

.container {
  position: relative;
  max-width: 1180px;
  margin: 0 auto;
  display: grid;
  gap: 22px;
}

.hero,
.summary-card,
.error-card,
.empty,
.action-bar {
  border: 1px solid var(--line);
  background: var(--surface);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  box-shadow: var(--shadow);
}

.hero {
  padding: 30px;
  border-radius: 32px;
}

.hero-top {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.pulse {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #111827;
  box-shadow: 0 0 0 0 rgba(17, 24, 39, 0.32);
  animation: pulse 2.4s infinite;
}

h1 {
  margin: 18px 0 10px;
  font-size: clamp(2.2rem, 4vw, 4rem);
  line-height: 0.95;
  letter-spacing: -0.05em;
}

.lead {
  margin: 0;
  max-width: 52ch;
  color: var(--muted);
  font-size: 15px;
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.action-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 44px;
  padding: 0 18px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.74);
  color: var(--text);
  text-decoration: none;
  font-size: 13px;
  font-weight: 700;
  transition: transform 180ms ease, box-shadow 180ms ease, background 180ms ease;
}

.action-link.primary {
  border-color: transparent;
  background: linear-gradient(135deg, #15171c 0%, #232735 100%);
  color: #fff;
  box-shadow: 0 20px 44px rgba(15, 23, 42, 0.16);
}

.action-link:hover {
  transform: translateY(-2px);
}

.meta-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 16px;
  margin-top: 24px;
}

.meta-card,
.source-card {
  border-radius: 24px;
  border: 1px solid rgba(15, 23, 42, 0.07);
  background: rgba(255, 255, 255, 0.7);
  padding: 18px 20px;
}

.meta-label {
  margin: 0 0 8px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.issue {
  font-size: 15px;
  line-height: 1.7;
}

.meta-stack {
  display: grid;
  gap: 8px;
  color: var(--muted);
  font-size: 13px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.summary-card {
  padding: 22px 20px;
  border-radius: 28px;
  animation: cardRise 620ms var(--ease) both;
}

.summary-card:nth-child(2) { animation-delay: 60ms; }
.summary-card:nth-child(3) { animation-delay: 120ms; }
.summary-card:nth-child(4) { animation-delay: 180ms; }

.summary-card .kicker {
  margin: 0 0 10px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.summary-card .value {
  display: block;
  margin-bottom: 8px;
  font-size: 2rem;
  font-weight: 800;
  letter-spacing: -0.05em;
}

.summary-card .subvalue {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.55;
}

.error-list {
  display: grid;
  gap: 18px;
}

.error-card {
  border-radius: 30px;
  padding: 24px;
  animation: cardRise 700ms var(--ease) both;
}

.error-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
}

.error-main {
  min-width: 0;
}

.exc-class {
  display: inline-block;
  margin-bottom: 10px;
  padding: 9px 12px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.05);
  border: 1px solid rgba(15, 23, 42, 0.08);
  color: #111827;
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}

.message {
  margin: 0;
  color: #222833;
  font-size: 17px;
  line-height: 1.55;
  letter-spacing: -0.02em;
}

.badges {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.badge {
  display: inline-flex;
  align-items: center;
  padding: 10px 14px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid transparent;
}

.count-badge {
  background: rgba(15, 23, 42, 0.07);
  color: #111827;
  border-color: rgba(15, 23, 42, 0.09);
}

.supporting {
  display: grid;
  grid-template-columns: 1.2fr 0.8fr;
  gap: 14px;
  margin-top: 18px;
}

.panel {
  padding: 18px;
  border-radius: 22px;
  border: 1px solid rgba(15, 23, 42, 0.07);
  background: rgba(255, 255, 255, 0.72);
}

.panel h3 {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.timeline {
  display: grid;
  gap: 8px;
  color: var(--muted);
  font-size: 13px;
}

.fix-box {
  background: linear-gradient(180deg, rgba(240, 249, 244, 0.88), rgba(255, 255, 255, 0.82));
}

.fix-box p {
  margin: 0 0 10px;
  color: #334155;
  font-size: 13px;
  line-height: 1.6;
}

.fix-box p:last-child {
  margin-bottom: 0;
}

details {
  margin-top: 18px;
  border-radius: 22px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(248, 249, 252, 0.82);
  overflow: hidden;
}

summary {
  cursor: pointer;
  list-style: none;
  padding: 16px 18px;
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

summary::-webkit-details-marker {
  display: none;
}

pre {
  margin: 0;
  padding: 0 18px 18px;
  color: #dbe4f0;
  background: linear-gradient(180deg, #10131a, #131827);
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
  font-size: 12px;
  line-height: 1.65;
  overflow-x: auto;
}

.empty {
  padding: 56px 28px;
  text-align: center;
  border-radius: 30px;
  color: var(--muted);
}

.empty strong {
  display: block;
  margin-bottom: 10px;
  font-size: 1.3rem;
  color: var(--text);
  letter-spacing: -0.03em;
}

.action-bar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 18px 22px;
  border-radius: 26px;
  color: var(--muted);
  font-size: 13px;
}

@media (max-width: 980px) {
  .meta-grid,
  .supporting,
  .summary-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 720px) {
  .shell {
    padding: 18px 14px 32px;
  }

  .hero,
  .summary-card,
  .error-card,
  .empty,
  .action-bar {
    border-radius: 24px;
  }

  .hero,
  .summary-card,
  .error-card {
    padding: 20px 18px;
  }

  .hero-top,
  .error-card-header,
  .badges,
  .action-bar {
    flex-direction: column;
    align-items: flex-start;
  }

  .meta-grid,
  .summary-grid,
  .supporting {
    grid-template-columns: 1fr;
  }
}

@keyframes pageFadeIn {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes cardRise {
  from { opacity: 0; transform: translateY(22px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(17, 24, 39, 0.32); }
  70% { box-shadow: 0 0 0 10px rgba(17, 24, 39, 0); }
  100% { box-shadow: 0 0 0 0 rgba(17, 24, 39, 0); }
}
"""


def _relevance_badge(relevance: str) -> str:
    fg, bg, border = RELEVANCE_COLOR.get(relevance, RELEVANCE_COLOR["unknown"])
    return (
        f'<span class="badge" style="color:{fg};background:{bg};border-color:{border}">'
        f"{html.escape(relevance)} relevance</span>"
    )


def generate_html_report(
    issue_description: str,
    window_start: datetime,
    window_end: datetime,
    groups: List,
    suggestions: dict,
    source_label: str = "",
) -> str:
    """suggestions: dict mapping group.fingerprint -> suggestion dict from llm_suggest.suggest_fix"""

    total_occurrences = sum(g.count for g in groups)
    high_relevance = 0
    medium_relevance = 0
    unknown_relevance = 0

    for sug in suggestions.values():
        relevance = sug.get("relevance", "unknown")
        if relevance == "high":
            high_relevance += 1
        elif relevance == "medium":
            medium_relevance += 1
        elif relevance == "unknown":
            unknown_relevance += 1

    cards = []
    for idx, g in enumerate(groups, start=1):
        sug = suggestions.get(g.fingerprint, {})
        fix_html = ""
        if sug.get("root_cause") or sug.get("suggested_fix"):
            fix_html = f"""
            <div class="panel fix-box">
                <h3>Suggested diagnosis & fix</h3>
                <p><strong>Root cause:</strong> {html.escape(sug.get('root_cause',''))}</p>
                {"<p><strong>Fix:</strong> " + html.escape(sug.get('suggested_fix','')) + "</p>" if sug.get('suggested_fix') else ""}
                {"<p><strong>Hybris context:</strong> " + html.escape(sug.get('hybris_context','')) + "</p>" if sug.get('hybris_context') else ""}
            </div>"""

        cards.append(f"""
        <article class="error-card" style="animation-delay:{idx * 70}ms;">
            <div class="error-card-header">
                <div class="error-main">
                    <div class="exc-class">{html.escape(g.exception_class)}</div>
                    <p class="message">{html.escape(g.message[:400])}</p>
                </div>
                <div class="badges">
                    {_relevance_badge(sug.get('relevance','unknown'))}
                    <span class="count-badge">{g.count} occurrence{'s' if g.count != 1 else ''}</span>
                </div>
            </div>
            <div class="supporting">
                <div class="panel">
                    <h3>Incident timing</h3>
                    <div class="timeline">
                        <div><strong>First seen:</strong> {g.first_seen}</div>
                        <div><strong>Last seen:</strong> {g.last_seen}</div>
                        <div><strong>Fingerprint:</strong> {html.escape(g.fingerprint[:160])}</div>
                    </div>
                </div>
                {fix_html if fix_html else '<div class="panel"><h3>Suggested diagnosis & fix</h3><p>AI guidance was not available for this error group.</p></div>'}
            </div>
            <details>
                <summary>View sample stack trace</summary>
                <pre>{html.escape(g.sample_entry.raw_text)}</pre>
            </details>
        </article>
        """)

    body = "\n".join(cards) if cards else (
        '<div class="empty"><strong>No errors found in this time window.</strong>'
        "The parser completed successfully, but nothing in the selected range matched the current error detection rules.</div>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hybris Log Analysis Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<div class="shell">
  <div class="container">
    <section class="hero">
      <div class="hero-top">
        <div>
          <div class="eyebrow"><span class="pulse"></span> Analysis Dashboard</div>
          <h1>Hybris incident report</h1>
          <p class="lead">Clustered failures, time-bounded evidence, and AI-assisted diagnosis from the selected production incident window.</p>
        </div>
        <div class="hero-actions">
          <a class="action-link" href="/">New analysis</a>
          <a class="action-link primary" href="/download">Download report</a>
        </div>
      </div>

      <div class="meta-grid">
        <div class="meta-card">
          <p class="meta-label">Issue Description</p>
          <div class="issue">{html.escape(issue_description)}</div>
        </div>
        <div class="source-card">
          <p class="meta-label">Run Metadata</p>
          <div class="meta-stack">
            <div><strong>Window:</strong> {window_start} &rarr; {window_end}</div>
            {"<div><strong>Source:</strong> " + html.escape(source_label) + "</div>" if source_label else ""}
            <div><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
          </div>
        </div>
      </div>
    </section>

    <section class="summary-grid">
      <div class="summary-card">
        <p class="kicker">Distinct Error Groups</p>
        <span class="value">{len(groups)}</span>
        <div class="subvalue">Unique clustered failures detected in the chosen time window.</div>
      </div>
      <div class="summary-card">
        <p class="kicker">Total Occurrences</p>
        <span class="value">{total_occurrences}</span>
        <div class="subvalue">Combined repeat count across every grouped error.</div>
      </div>
      <div class="summary-card">
        <p class="kicker">High Relevance</p>
        <span class="value">{high_relevance}</span>
        <div class="subvalue">Error groups judged strongly related to the reported issue.</div>
      </div>
      <div class="summary-card">
        <p class="kicker">AI Coverage</p>
        <span class="value">{len(groups) - unknown_relevance}/{len(groups) if groups else 0}</span>
        <div class="subvalue">{medium_relevance} medium-relevance group(s), {unknown_relevance} unknown.</div>
      </div>
    </section>

    <section class="error-list">
      {body}
    </section>

    <section class="action-bar">
      <div>The report is self-contained HTML, so it can be archived or shared as-is.</div>
      <a class="action-link primary" href="/download">Download standalone file</a>
    </div>
  </div>
</div>
</body>
</html>"""
