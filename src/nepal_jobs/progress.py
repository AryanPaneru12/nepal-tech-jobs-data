from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4


class ProgressCallback(Protocol):
    def __call__(self, event: str, fields: dict[str, Any] | None = None) -> None: ...


class ProgressReporter:
    """Write concise terminal progress and machine-readable JSONL events."""

    def __init__(self, log_dir: Path, command: str, *, echo: bool = True) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        safe_command = command.replace(" ", "-").replace("/", "-")
        self.path = log_dir / f"{timestamp}-{safe_command}-{uuid4().hex[:8]}.jsonl"
        self.command = command
        self.echo = echo
        self._lock = Lock()

    def __call__(self, event: str, fields: dict[str, Any] | None = None) -> None:
        values = fields or {}
        now = datetime.now(UTC)
        record = {
            "timestamp": now.isoformat(),
            "command": self.command,
            "event": event,
            **values,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
            if self.echo:
                print(_terminal_line(now, event, values), flush=True)


def _terminal_line(timestamp: datetime, event: str, fields: dict[str, Any]) -> str:
    details = " ".join(
        f"{key}={_display(value)}" for key, value in sorted(fields.items()) if value is not None
    )
    prefix = timestamp.astimezone().strftime("[%H:%M:%S]")
    return f"{prefix} {event}" + (f" {details}" if details else "")


def _display(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    text = str(value).replace("\n", " ")
    return f'"{text}"' if " " in text else text
