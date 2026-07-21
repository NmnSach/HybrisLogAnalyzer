# Hybris Log Analyzer

A local web app that fetches SAP Hybris log files over SFTP, isolates errors
within a described time window, groups similar errors together, and
generates an HTML report with AI-suggested root causes and fixes.

## How it works

1. You describe the issue, the date, and the time window in a web form.
2. The app connects to your log server over **SFTP** and pulls the relevant
   log file (or you can upload a log file directly instead).
3. It parses every log entry, keeping multi-line stack traces intact.
4. Entries inside your time window are filtered.
5. Errors are detected by content (not by log level — Hybris `wrapper.log`
   marks everything `INFO` regardless of real severity) and grouped by a
   fingerprint of exception type + root cause + top stack frame, so 200
   repeats of the same error become one entry with a count.
6. Each *distinct* error group (not every occurrence) is sent to Claude
   along with your issue description, and comes back with a likely root
   cause and suggested fix.
7. Everything renders as a single self-contained HTML report.

## Project structure

```
hybris-log-analyzer/
├── app.py                 # Flask app: routes, SFTP fetch, orchestration
├── log_parser.py           # Log parsing, time-window filtering, clustering
├── llm_suggest.py           # Calls Claude for root cause / fix suggestions
├── report_generator.py      # Builds the final HTML report
├── templates/
│   └── index.html          # The input form
├── requirements.txt
├── .env.example             # Copy to .env and fill in your API key
└── .gitignore
```

## Setup

```bash
git clone <your-repo-url>
cd hybris-log-analyzer

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY (optional — without it the report
# still generates, just without AI fix suggestions)
```

## Run

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

## Using it

- **Log source:** choose "Fetch via SFTP" and enter the host, port
  (default 22), username, password, and the full remote path to the log
  file (e.g. `/opt/hybris/data/log/tomcat/wrapper.log`). Or choose
  "Upload file" if you'd rather pull the file down with WinSCP yourself
  first and upload it locally.
- **Time window:** if the end time is earlier than the start time, the
  window is treated as crossing midnight.
- Click **Analyze logs** — the report renders in your browser. Add a
  `/download` route call (already wired up) to save it as a standalone
  `.html` file.

## Supported log formats

Currently supports:
- Tanuki wrapper log format (`wrapper.log`):
  `INFO   | jvm 1    | main    | 2026/07/20 00:00:10.287 | <content>`
- Standard log4j2 format (`hybris.log`):
  `2026-07-20 14:32:10,123 ERROR [thread] <content>`

If your environment uses a different pattern layout, add a new entry to
`LINE_PATTERNS` in `log_parser.py` — see the comments there for the format.

## Notes on SFTP vs SCP

This app uses SFTP (via `paramiko`), not SCP. If your server's SSH daemon
has the SFTP subsystem enabled — true for virtually all OpenSSH setups,
including what WinSCP connects to by default — this works identically to
what you'd get browsing the server in WinSCP. Check WinSCP's session
settings under "File protocol" if you're unsure which your server offers.

## Security notes

- SFTP credentials are submitted via the form and used only for that
  request; they are not stored or logged by the app.
- For anything beyond local/personal use, swap the password field for
  SSH key-based auth (`paramiko.SFTPClient` supports `pkey=`) rather than
  passing passwords through a web form.
- `.env` is gitignored — never commit real API keys or credentials.

## Extending

- **Large log files:** `fetch_via_sftp` currently reads the whole file
  into memory. For multi-GB logs, switch to streaming line-by-line via
  `sftp.open(path).readline()`, or pre-filter server-side with a remote
  `grep`/`sed` command over SSH exec before transferring.
- **SCP instead of SFTP:** if your server only supports SCP, replace
  `fetch_via_sftp` with the `scp` package layered on `paramiko.Transport`.
- **Multiple log sources:** Hybris often spans multiple nodes/logs
  (storefront, backoffice, admin) — you can loop `fetch_via_sftp` over
  several paths and merge the parsed entries before clustering.
