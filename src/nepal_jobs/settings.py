from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    root: Path
    data_dir: Path
    db_path: Path
    raw_dir: Path
    source_dir: Path
    user_agent: str
    contact_email: str
    brave_api_key: str | None
    google_places_api_key: str | None
    r2_endpoint_url: str | None
    r2_bucket: str | None
    r2_access_key_id: str | None
    r2_secret_access_key: str | None

    @classmethod
    def load(cls, root: Path | None = None) -> Settings:
        project_root = (root or Path.cwd()).resolve()
        data_dir = _resolve(project_root, os.getenv("NJOBS_DATA_DIR", "data"))
        return cls(
            root=project_root,
            data_dir=data_dir,
            db_path=_resolve(
                project_root, os.getenv("NJOBS_DB_PATH", "data/work/nepal_jobs.duckdb")
            ),
            raw_dir=_resolve(project_root, os.getenv("NJOBS_RAW_DIR", "data/private/raw")),
            source_dir=project_root / "config" / "sources",
            user_agent=os.getenv(
                "NJOBS_USER_AGENT",
                "NepalJobsData/0.1 (+https://github.com/nepal-jobs-data; contact: unset)",
            ),
            contact_email=os.getenv("NJOBS_CONTACT_EMAIL", "unset@example.com"),
            brave_api_key=os.getenv("BRAVE_SEARCH_API_KEY") or None,
            google_places_api_key=os.getenv("GOOGLE_PLACES_API_KEY") or None,
            r2_endpoint_url=os.getenv("R2_ENDPOINT_URL") or None,
            r2_bucket=os.getenv("R2_BUCKET") or None,
            r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID") or None,
            r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY") or None,
        )

    def ensure_runtime_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "current").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "reports").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)


def _resolve(root: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
