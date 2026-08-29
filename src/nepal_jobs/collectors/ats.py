from __future__ import annotations

from nepal_jobs.models import CollectionBatch, CompanyCandidate, JobCandidate
from nepal_jobs.normalization import infer_workplace, parse_datetime

from .base import Collector, required_parameter


class GreenhouseCollector(Collector):
    def collect(self, client, source) -> CollectionBatch:  # type: ignore[no-untyped-def]
        documents, jobs, companies = [], [], []
        for board in required_parameter(source, "boards"):
            token = board["token"] if isinstance(board, dict) else str(board)
            company_name = board.get("company", token) if isinstance(board, dict) else token
            website = board.get("website") if isinstance(board, dict) else None
            url = f"{str(source.base_url).rstrip('/')}/{token}/jobs?content=true"
            document = client.fetch(url, source)
            documents.append(document)
            payload = self.json(document)
            companies.append(_company(source.id, url, company_name, website))
            for row in payload.get("jobs", []):
                location = (row.get("location") or {}).get("name")
                jobs.append(
                    JobCandidate(
                        source_id=source.id,
                        source_url=row.get("absolute_url") or url,
                        external_id=str(row["id"]),
                        company_name=company_name,
                        company_website=website,
                        title=row["title"],
                        description=row.get("content"),
                        apply_url=row.get("absolute_url"),
                        location_text=location,
                        candidate_location=location,
                        workplace_type=infer_workplace(row["title"], location, row.get("content")),
                        posted_at=parse_datetime(row.get("updated_at")),
                    )
                )
        return CollectionBatch(
            companies=companies, jobs=jobs, documents=documents, full_snapshot=True
        )


class LeverCollector(Collector):
    def collect(self, client, source) -> CollectionBatch:  # type: ignore[no-untyped-def]
        documents, jobs, companies = [], [], []
        for board in required_parameter(source, "boards"):
            token = board["token"] if isinstance(board, dict) else str(board)
            company_name = board.get("company", token) if isinstance(board, dict) else token
            website = board.get("website") if isinstance(board, dict) else None
            url = f"{str(source.base_url).rstrip('/')}/{token}?mode=json"
            document = client.fetch(url, source)
            documents.append(document)
            companies.append(_company(source.id, url, company_name, website))
            for row in self.json(document):
                categories = row.get("categories") or {}
                location = categories.get("location")
                description = " ".join(
                    filter(None, (row.get("description"), row.get("additional")))
                )
                jobs.append(
                    JobCandidate(
                        source_id=source.id,
                        source_url=row.get("hostedUrl") or row.get("applyUrl") or url,
                        external_id=row.get("id"),
                        company_name=company_name,
                        company_website=website,
                        title=row["text"],
                        description=description,
                        apply_url=row.get("applyUrl") or row.get("hostedUrl"),
                        location_text=location,
                        candidate_location=location,
                        employment_type=categories.get("commitment"),
                        workplace_type=infer_workplace(row["text"], location, description),
                        posted_at=parse_datetime(row.get("createdAt")),
                    )
                )
        return CollectionBatch(
            companies=companies, jobs=jobs, documents=documents, full_snapshot=True
        )


class AshbyCollector(Collector):
    def collect(self, client, source) -> CollectionBatch:  # type: ignore[no-untyped-def]
        documents, jobs, companies = [], [], []
        for board in required_parameter(source, "boards"):
            token = board["token"] if isinstance(board, dict) else str(board)
            company_name = board.get("company", token) if isinstance(board, dict) else token
            website = board.get("website") if isinstance(board, dict) else None
            url = f"{str(source.base_url).rstrip('/')}/{token}?includeCompensation=true"
            document = client.fetch(url, source)
            documents.append(document)
            companies.append(_company(source.id, url, company_name, website))
            for row in self.json(document).get("jobs", []):
                location = row.get("location")
                jobs.append(
                    JobCandidate(
                        source_id=source.id,
                        source_url=row.get("jobUrl") or row.get("applyUrl") or url,
                        external_id=row.get("id") or row.get("jobUrl"),
                        company_name=company_name,
                        company_website=website,
                        title=row["title"],
                        description=row.get("descriptionHtml") or row.get("descriptionPlain"),
                        apply_url=row.get("applyUrl") or row.get("jobUrl"),
                        location_text=location,
                        candidate_location=location,
                        employment_type=row.get("employmentType"),
                        workplace_type=infer_workplace(
                            row["title"], location, row.get("workplaceType")
                        ),
                        posted_at=parse_datetime(row.get("publishedAt")),
                    )
                )
        return CollectionBatch(
            companies=companies, jobs=jobs, documents=documents, full_snapshot=True
        )


def _company(source_id: str, source_url: str, name: str, website: str | None) -> CompanyCandidate:
    return CompanyCandidate(
        source_id=source_id,
        source_url=source_url,
        name=name,
        website=website,
        careers_url=source_url,
        sectors=["technology"],
        confidence=0.85,
    )
