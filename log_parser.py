"""
log_parser.py
Parses Hybris/Tomcat-style wrapper.log files (and standard log4j2-formatted
hybris.log files), isolates errors within a time window, and clusters
similar errors together.

Supported line format (Tanuki JVM wrapper, e.g. wrapper.log):
    INFO   | jvm 1    | main    | 2026/07/20 00:00:10.287 | <content>

Also handles the more common log4j2 format used in hybris.log:
    2026-07-20 14:32:10,123 ERROR [http-nio-9002-exec-3] SomeClass : message

Add more patterns to LINE_PATTERNS if your environment uses a different
log4j2 pattern layout.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


# ---------------------------------------------------------------------------
# Line-level patterns. Each has a compiled regex with named groups:
#   ts (timestamp string), content (rest of the line)
# and a matching strptime format for ts.
# ---------------------------------------------------------------------------
LINE_PATTERNS = [
    {
        "name": "wrapper_log",
        "regex": re.compile(
            r"^(?P<level>\w+)\s*\|\s*jvm\s*\d+\s*\|\s*[\w\-]*\s*\|\s*"
            r"(?P<ts>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s*\|\s?(?P<content>.*)$"
        ),
        "ts_formats": ["%Y/%m/%d %H:%M:%S.%f"],
    },
    {
        "name": "log4j2_standard",
        "regex": re.compile(
            r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,.]\d{3})\s+"
            r"(?P<level>[A-Z]+)\s+(?P<content>.*)$"
        ),
        "ts_formats": ["%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S.%f"],
    },
]

# A continuation line belongs to the previous entry rather than starting a
# new one: stack frames, "Caused by:", and "... N more" truncation markers.
CONTINUATION_RE = re.compile(r"^\s*(at\s|Caused by:|\.\.\.\s*\d+\s+more)")

LEVEL_ALIASES = {
    "TRACE": "trace",
    "DEBUG": "debug",
    "INFO": "info",
    "WARN": "warning",
    "WARNING": "warning",
    "ERROR": "error",
    "FATAL": "error",
}

SEVERITY_PRIORITY = {
    "trace": 0,
    "debug": 1,
    "info": 2,
    "warning": 3,
    "error": 4,
}

CONTENT_LEVEL_RE = re.compile(r"^\s*\[?(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\]?\b[:\s-]*")

ERROR_CONTENT_RE = re.compile(
    r"(?:^|\s)([\w$]+\.)*[\w$]*(Exception|Error)\b|"
    r"\b(ERROR|FATAL|SEVERE|FAILED|FAILURE)\b|"
    r"\bCaused by:"
)
WARNING_CONTENT_RE = re.compile(
    r"\bWARN(?:ING)?\b|"
    r"\b(DEPRECATED|TIMEOUT|RETRY(?:ING)?|SLOW|UNAVAILABLE|BLOCKED)\b"
)

# Extracts a fully-qualified exception/error class name, e.g.
# "de.hybris.platform.jalo.JaloBusinessException"
EXCEPTION_CLASS_RE = re.compile(r"(([\w$]+\.)+[\w$]*(?:Exception|Error))\b")

# Extracts the class+method from a stack frame line, ignoring the line number,
# e.g. "at de.hybris.platform.jalo.media.Media.getDataFromStream(Media.java:773)"
#   -> "de.hybris.platform.jalo.media.Media.getDataFromStream"
STACK_FRAME_RE = re.compile(r"at\s+([\w$.<>]+)\(")

# Normalizes dynamic tokens (numeric IDs, hex, long digit runs) in messages
# so that otherwise-identical errors with different IDs cluster together.
DYNAMIC_TOKEN_RE = re.compile(r"\b(0x[0-9a-fA-F]+|\d{4,}|\d+)\b")


def normalize_level(level: Optional[str]) -> Optional[str]:
    if not level:
        return None
    return LEVEL_ALIASES.get(level.strip().upper())


def parse_timestamp(ts_str: str, ts_formats: List[str]) -> Optional[datetime]:
    for fmt in ts_formats:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    return None


def infer_content_level(content: str) -> Optional[str]:
    match = CONTENT_LEVEL_RE.match(content)
    if match:
        return normalize_level(match.group(1))
    if ERROR_CONTENT_RE.search(content):
        return "error"
    if WARNING_CONTENT_RE.search(content):
        return "warning"
    return None


def pick_severity(*levels: Optional[str]) -> str:
    candidates = [level for level in levels if level]
    if not candidates:
        return "info"
    return max(candidates, key=lambda level: SEVERITY_PRIORITY.get(level, -1))


@dataclass
class LogEntry:
    timestamp: datetime
    severity: str = "info"
    declared_level: Optional[str] = None
    raw_lines: List[str] = field(default_factory=list)
    content_lines: List[str] = field(default_factory=list)

    @property
    def first_content(self) -> str:
        return self.content_lines[0] if self.content_lines else ""

    @property
    def is_error(self) -> bool:
        return self.severity == "error"

    @property
    def is_warning(self) -> bool:
        return self.severity == "warning"

    @property
    def is_issue(self) -> bool:
        return self.severity in {"error", "warning"}

    @property
    def exception_class(self) -> Optional[str]:
        for line in self.content_lines:
            m = EXCEPTION_CLASS_RE.search(line)
            if m:
                return m.group(1)
        return None

    @property
    def root_cause_class(self) -> Optional[str]:
        """Last 'Caused by:' exception class, if any (the true root cause)."""
        root = None
        for line in self.content_lines:
            if line.strip().startswith("Caused by:"):
                m = EXCEPTION_CLASS_RE.search(line)
                if m:
                    root = m.group(1)
        return root

    @property
    def top_frame(self) -> Optional[str]:
        for line in self.content_lines:
            m = STACK_FRAME_RE.search(line)
            if m:
                return m.group(1)
        return None

    @property
    def message(self) -> str:
        """Human-readable message from the first line (class stripped)."""
        content = CONTENT_LEVEL_RE.sub("", self.first_content, count=1).strip()
        m = EXCEPTION_CLASS_RE.search(content)
        if m:
            return content[m.end():].lstrip(": ").strip()
        return content

    @property
    def raw_text(self) -> str:
        return "\n".join(self.raw_lines)

    def fingerprint(self) -> str:
        """Groups occurrences of 'the same' error, ignoring IDs/values."""
        cause = self.root_cause_class or self.exception_class or (
            "Warning" if self.is_warning else "UnknownError"
        )
        frame = self.top_frame or ""
        norm_msg = DYNAMIC_TOKEN_RE.sub("#", self.message)[:120]
        return f"{self.severity}|{cause}|{frame}|{norm_msg}"


def detect_pattern(sample_lines: List[str]):
    """Pick the line pattern that matches the most lines in a sample."""
    best, best_score = None, 0
    for pat in LINE_PATTERNS:
        score = sum(1 for ln in sample_lines if pat["regex"].match(ln))
        if score > best_score:
            best, best_score = pat, score
    return best


def parse_log(text: str) -> List[LogEntry]:
    """Parse raw log text into a list of LogEntry objects (one per
    top-level statement; multi-line stack traces are kept together)."""
    lines = text.splitlines()
    pattern = detect_pattern(lines[:200])
    if pattern is None:
        raise ValueError(
            "Could not detect a known log format. Add a new entry to "
            "LINE_PATTERNS in log_parser.py for this log's layout."
        )

    entries: List[LogEntry] = []
    current: Optional[LogEntry] = None

    for line in lines:
        m = pattern["regex"].match(line)
        if not m:
            # Line didn't match the timestamp pattern at all (e.g. a raw
            # stdout line with no prefix) — treat as continuation if we
            # have an open entry, otherwise skip.
            if current is not None:
                current.raw_lines.append(line)
                current.content_lines.append(line)
            continue

        ts_str, content = m.group("ts"), m.group("content")
        declared_level = normalize_level(m.groupdict().get("level"))
        inferred_level = infer_content_level(content)
        severity = pick_severity(declared_level, inferred_level)
        ts = parse_timestamp(ts_str, pattern["ts_formats"])
        if ts is None:
            ts = current.timestamp if current else None

        if current is not None and CONTINUATION_RE.match(content):
            current.raw_lines.append(line)
            current.content_lines.append(content)
            current.severity = pick_severity(current.severity, severity)
        else:
            if current is not None:
                entries.append(current)
            current = LogEntry(
                timestamp=ts,
                severity=severity,
                declared_level=declared_level,
                raw_lines=[line],
                content_lines=[content],
            )

    if current is not None:
        entries.append(current)

    return entries


def filter_by_window(entries: List[LogEntry], start: datetime, end: datetime) -> List[LogEntry]:
    return [e for e in entries if e.timestamp and start <= e.timestamp <= end]


@dataclass
class ErrorGroup:
    fingerprint: str
    severity: str
    exception_class: str
    message: str
    sample_entry: LogEntry
    occurrences: List[LogEntry] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.occurrences)

    @property
    def first_seen(self) -> datetime:
        return min(e.timestamp for e in self.occurrences)

    @property
    def last_seen(self) -> datetime:
        return max(e.timestamp for e in self.occurrences)


def cluster_errors(entries: List[LogEntry]) -> List[ErrorGroup]:
    """Group warning/error entries that represent the same underlying issue."""
    groups = {}
    for e in entries:
        if not e.is_issue:
            continue
        fp = e.fingerprint()
        if fp not in groups:
            groups[fp] = ErrorGroup(
                fingerprint=fp,
                severity=e.severity,
                exception_class=e.root_cause_class or e.exception_class or "UnknownError",
                message=e.message,
                sample_entry=e,
            )
        groups[fp].occurrences.append(e)

    # Most frequent first
    return sorted(groups.values(), key=lambda g: g.count, reverse=True)


if __name__ == "__main__":
    # Quick self-test against sample.log
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "sample_logs/wrapper_sample.log"
    with open(path, "r", errors="replace") as f:
        text = f.read()

    entries = parse_log(text)
    print(f"Parsed {len(entries)} entries")

    errors = [e for e in entries if e.is_error]
    print(f"Found {len(errors)} error entries")

    groups = cluster_errors(entries)
    print(f"Clustered into {len(groups)} distinct error group(s)\n")
    for g in groups:
        print(f"[{g.count}x] {g.exception_class}")
        print(f"    message: {g.message[:100]}")
        print(f"    first: {g.first_seen}  last: {g.last_seen}")
        print(f"    top frame: {g.sample_entry.top_frame}")
        print()
