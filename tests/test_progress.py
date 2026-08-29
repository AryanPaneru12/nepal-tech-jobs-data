import json
from pathlib import Path

from nepal_jobs.progress import ProgressReporter


def test_progress_reporter_writes_structured_jsonl(tmp_path: Path) -> None:
    reporter = ProgressReporter(tmp_path / "logs", "run-weekly", echo=False)

    reporter("fetch_completed", {"source": "fixture", "request": 2, "elapsed": 1.25})

    records = [json.loads(line) for line in reporter.path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["command"] == "run-weekly"
    assert records[0]["event"] == "fetch_completed"
    assert records[0]["source"] == "fixture"
    assert records[0]["request"] == 2
    assert records[0]["timestamp"].endswith("+00:00")


def test_progress_reporter_creates_unique_files(tmp_path: Path) -> None:
    first = ProgressReporter(tmp_path, "collect", echo=False)
    second = ProgressReporter(tmp_path, "collect", echo=False)

    assert first.path != second.path
