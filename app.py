"""
app.py
Local web app for analyzing Hybris log files.

Run:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...      # optional, enables fix suggestions
    python app.py
Then open http://127.0.0.1:5000
"""

import io
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, render_template, request, send_file

load_dotenv()

from log_parser import parse_log, filter_by_window, cluster_errors
from llm_suggest import suggest_fix
from report_generator import generate_html_report

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB upload cap

LAST_REPORT = {"html": None, "filename": None}


def fetch_via_sftp(host, port, username, password, remote_path) -> str:
    import paramiko

    transport = paramiko.Transport((host, int(port or 22)))
    try:
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            with sftp.open(remote_path, "r") as f:
                f.prefetch()
                data = f.read()
        finally:
            sftp.close()
    finally:
        transport.close()

    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    return data


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    issue_description = request.form.get("issue_description", "").strip()
    date_str = request.form.get("date", "")
    start_time_str = request.form.get("start_time", "")
    end_time_str = request.form.get("end_time", "")
    source_mode = request.form.get("source_mode", "upload")

    try:
        window_start = datetime.strptime(f"{date_str} {start_time_str}", "%Y-%m-%d %H:%M")
        window_end = datetime.strptime(f"{date_str} {end_time_str}", "%Y-%m-%d %H:%M")
        if window_end <= window_start:
            window_end += timedelta(days=1)  # window crosses midnight
    except ValueError:
        return render_template("index.html", error="Invalid date/time values."), 400

    # --- Get the log text, either via SFTP or a direct upload ---
    source_label = ""
    try:
        if source_mode == "sftp":
            host = request.form.get("sftp_host", "").strip()
            port = request.form.get("sftp_port", "22").strip()
            username = request.form.get("sftp_username", "").strip()
            password = request.form.get("sftp_password", "")
            remote_path = request.form.get("sftp_path", "").strip()
            if not (host and username and remote_path):
                return render_template("index.html", error="Missing SFTP host/username/path."), 400
            log_text = fetch_via_sftp(host, port, username, password, remote_path)
            source_label = f"{username}@{host}:{remote_path}"
        else:
            uploaded = request.files.get("log_file")
            if not uploaded or uploaded.filename == "":
                return render_template("index.html", error="No log file uploaded."), 400
            log_text = uploaded.read().decode("utf-8", errors="replace")
            source_label = uploaded.filename
    except Exception as exc:  # noqa: BLE001
        return render_template("index.html", error=f"Failed to retrieve log: {exc}"), 500

    # --- Parse, filter, cluster ---
    try:
        entries = parse_log(log_text)
    except ValueError as exc:
        return render_template("index.html", error=str(exc)), 400

    windowed = filter_by_window(entries, window_start, window_end)
    groups = cluster_errors(windowed)

    # --- Get fix suggestions per distinct error group ---
    suggestions = {}
    for g in groups:
        suggestions[g.fingerprint] = suggest_fix(issue_description, g)

    # --- Render report ---
    report_html = generate_html_report(
        issue_description, window_start, window_end, groups, suggestions, source_label
    )
    LAST_REPORT["html"] = report_html
    LAST_REPORT["filename"] = f"hybris_log_report_{window_start.strftime('%Y%m%d_%H%M')}.html"

    return report_html


@app.route("/download")
def download():
    if not LAST_REPORT["html"]:
        return "No report generated yet.", 404
    buf = io.BytesIO(LAST_REPORT["html"].encode("utf-8"))
    return send_file(
        buf,
        mimetype="text/html",
        as_attachment=True,
        download_name=LAST_REPORT["filename"],
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
