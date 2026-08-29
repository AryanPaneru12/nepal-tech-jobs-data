from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import boto3
import zstandard

from .ids import content_hash
from .models import FetchedDocument, SourceDefinition


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    content_sha256: str
    pointer: str


class ArchiveStore(Protocol):
    def put(
        self, document: FetchedDocument, source: SourceDefinition, run_id: str
    ) -> ArchiveResult: ...


class LocalArchiveStore:
    def __init__(self, root: Path):
        self.root = root

    def put(
        self, document: FetchedDocument, source: SourceDefinition, run_id: str
    ) -> ArchiveResult:
        digest = content_hash(document.content)
        folder = self.root / source.id / run_id
        folder.mkdir(parents=True, exist_ok=True)
        payload_path = folder / f"{digest}.bin.zst"
        metadata_path = folder / f"{digest}.meta.json"
        if not payload_path.exists():
            payload_path.write_bytes(zstandard.ZstdCompressor(level=9).compress(document.content))
            metadata_path.write_text(
                json.dumps(
                    {
                        "source_id": source.id,
                        "url": document.url,
                        "fetched_at": document.fetched_at.isoformat(),
                        "status_code": document.status_code,
                        "content_type": document.content_type,
                        "sha256": digest,
                        "retention_days": source.raw_retention_days,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return ArchiveResult(digest, str(payload_path.resolve()))


class S3ArchiveStore:
    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def put(
        self, document: FetchedDocument, source: SourceDefinition, run_id: str
    ) -> ArchiveResult:
        digest = content_hash(document.content)
        key = f"raw/{source.id}/{run_id}/{digest}.bin.zst"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=zstandard.ZstdCompressor(level=9).compress(document.content),
            ContentType="application/zstd",
            Metadata={
                "source-id": source.id,
                "fetched-at": document.fetched_at.isoformat(),
                "retention-days": str(source.raw_retention_days),
                "sha256": digest,
            },
        )
        return ArchiveResult(digest, f"s3://{self.bucket}/{key}")


def prune_local_archive(root: Path, source: SourceDefinition, now: datetime) -> int:
    removed = 0
    source_root = root / source.id
    if not source_root.exists():
        return 0
    for metadata_path in source_root.rglob("*.meta.json"):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(metadata["fetched_at"])
        if (now - fetched_at).days > source.raw_retention_days:
            payload_path = metadata_path.with_name(
                metadata_path.name.replace(".meta.json", ".bin.zst")
            )
            payload_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            removed += 1
    return removed
