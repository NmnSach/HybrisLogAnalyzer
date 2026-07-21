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
        "ts_format": "%Y/%m/%d %H:%M:%S.%f",
    },
    {
        "name": "log4j2_standard",
        "regex": re.compile(
            r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,.]\d{3})\s+"
            r"(?P<level>[A-Z]+)\s+(?P<content>.*)$"
        ),
        "ts_format": "%Y-%m-%d %H:%M:%S,%f",
    },
]

# A continuation line belongs to the previous entry rather than starting a
# new one: stack frames, "Caused by:", and "... N more" truncation markers.
CONTINUATION_RE = re.compile(r"^\s*(at\s|Caused by:|\.\.\.\s*\d+\s+more)")

# Detects whether an entry's first content line represents an actual error,
# independent of the wrapper-assigned log level (which in wrapper.log is
# always INFO regardless of real severity).
ERROR_CONTENT_RE = re.compile(
    r"(?:^|\s)([\w$]+\.)+[\w$]*(Exception|Error)\b|"
    r"\bERROR\b|\bFATAL\b|\bCaused by:"
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


@dataclass
class LogEntry:
    timestamp: datetime
    raw_lines: List[str] = field(default_factory=list)
    content_lines: List[str] = field(default_factory=list)

    @property
    def first_content(self) -> str:
        return self.content_lines[0] if self.content_lines else ""

    @property
    def is_error(self) -> bool:
        return bool(ERROR_CONTENT_RE.search(self.first_content))

    @property
    def exception_class(self) -> Optional[str]:
        m = EXCEPTION_CLASS_RE.search(self.first_content)
        return m.group(1) if m else None

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
        m = EXCEPTION_CLASS_RE.search(self.first_content)
        if m:
            return self.first_content[m.end():].lstrip(": ").strip()
        return self.first_content.strip()

    @property
    def raw_text(self) -> str:
        return "\n".join(self.raw_lines)

    def fingerprint(self) -> str:
        """Groups occurrences of 'the same' error, ignoring IDs/values."""
        cause = self.root_cause_class or self.exception_class or "UnknownError"
        frame = self.top_frame or ""
        norm_msg = DYNAMIC_TOKEN_RE.sub("#", self.message)[:120]
        return f"{cause}|{frame}|{norm_msg}"


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
        try:
            ts = datetime.strptime(ts_str, pattern["ts_format"])
        except ValueError:
            ts = current.timestamp if current else None

        if current is not None and CONTINUATION_RE.match(content):
            current.raw_lines.append(line)
            current.content_lines.append(content)
            if ts:
                current.timestamp = current.timestamp  # keep entry's start ts
        else:
            if current is not None:
                entries.append(current)
            current = LogEntry(timestamp=ts, raw_lines=[line], content_lines=[content])

    if current is not None:
        entries.append(current)

    return entries


def filter_by_window(entries: List[LogEntry], start: datetime, end: datetime) -> List[LogEntry]:
    return [e for e in entries if e.timestamp and start <= e.timestamp <= end]


@dataclass
class ErrorGroup:
    fingerprint: str
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
    """Group error entries that represent 'the same' underlying error."""
    groups = {}
    for e in entries:
        if not e.is_error:
            continue
        fp = e.fingerprint()
        if fp not in groups:
            groups[fp] = ErrorGroup(
                fingerprint=fp,
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
