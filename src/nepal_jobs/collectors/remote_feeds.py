from __future__ import annotations

from nepal_jobs.models import CollectionBatch, JobCandidate, WorkplaceType
from nepal_jobs.normalization import infer_workplace, parse_datetime

from .base import Collector


class RemoteOkCollector(Collector):
    def collect(self, client, source) -> CollectionBatch:  # type: ignore[no-untyped-def]
        url = str(source.base_url)
        document = client.fetch(url, source)
        payload = self.json(document)
        rows = (
            payload[1:]
            if isinstance(payload, list) and payload and "legal" in payload[0]
            else payload
        )
        jobs: list[JobCandidate] = []
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("position") or not row.get("company"):
                continue
            location = row.get("location") or "Worldwide"
            jobs.append(
                JobCandidate(
                    source_id=source.id,
                    source_url=row.get("url") or url,
                    external_id=str(row.get("id") or row.get("slug") or ""),
                    company_name=row["company"],
                    title=row["position"],
                    description=row.get("description"),
                    apply_url=row.get("apply_url") or row.get("url"),
                    location_text=location,
                    candidate_location=location,
                    employment_type=row.get("job_type"),
                    workplace_type=WorkplaceType.REMOTE,
                    salary_text=row.get("salary"),
                    skills=row.get("tags") or [],
                    posted_at=parse_datetime(row.get("date") or row.get("epoch")),
                    description_public=source.redistribution.value == "attributed",
                    attribution=source.attribution,
                )
            )
        return CollectionBatch(jobs=jobs, documents=[document], full_snapshot=True)


class RemotiveCollector(Collector):
    def collect(self, client, source) -> CollectionBatch:  # type: ignore[no-untyped-def]
        url = str(source.base_url)
        document = client.fetch(url, source)
        payload = self.json(document)
        jobs = [
            JobCandidate(
                source_id=source.id,
                source_url=row["url"],
                external_id=str(row["id"]),
                company_name=row["company_name"],
                title=row["title"],
                description=row.get("description"),
                apply_url=row["url"],
                location_text=row.get("candidate_required_location"),
                candidate_location=row.get("candidate_required_location"),
                employment_type=row.get("job_type"),
                workplace_type=WorkplaceType.REMOTE,
                salary_text=row.get("salary"),
                skills=[row["category"]] if row.get("category") else [],
                posted_at=parse_datetime(row.get("publication_date")),
                description_public=source.redistribution.value == "attributed",
                attribution=source.attribution,
            )
            for row in payload.get("jobs", [])
            if row.get("title") and row.get("company_name") and row.get("url")
        ]
        return CollectionBatch(jobs=jobs, documents=[document], full_snapshot=True)


class HimalayasCollector(Collector):
    def collect(self, client, source) -> CollectionBatch:  # type: ignore[no-untyped-def]
        base_url = str(source.base_url)
        cursor = None
        max_pages = int(source.parameters.get("max_pages", 100))
        documents = []
        jobs: list[JobCandidate] = []
        for _ in range(max_pages):
            url = f"{base_url}?limit=20" + (f"&cursor={cursor}" if cursor else "")
            document = client.fetch(url, source)
            documents.append(document)
            payload = self.json(document)
            rows = payload.get("jobs") or payload.get("data") or []
            for row in rows:
                location = (
                    row.get("locationRestrictions") or row.get("location") or row.get("country")
                )
                if isinstance(location, list):
                    location = ", ".join(str(item) for item in location)
                jobs.append(
                    JobCandidate(
                        source_id=source.id,
                        source_url=row.get("url") or row.get("applicationLink"),
                        external_id=str(row.get("guid") or row.get("id") or ""),
                        company_name=row.get("companyName") or row.get("company", {}).get("name"),
                        company_website=row.get("company", {}).get("website")
                        if isinstance(row.get("company"), dict)
                        else None,
                        title=row.get("title"),
                        description=row.get("description"),
                        apply_url=row.get("applicationLink") or row.get("url"),
                        location_text=location,
                        candidate_location=location,
                        employment_type=row.get("employmentType"),
                        workplace_type=infer_workplace("remote", location),
                        salary_text=row.get("salaryDescription"),
                        skills=row.get("categories") or [],
                        posted_at=parse_datetime(row.get("pubDate")),
                        expires_at=parse_datetime(row.get("expiryDate")),
                        description_public=source.redistribution.value == "attributed",
                        attribution=source.attribution,
                    )
                )
            cursor = payload.get("nextCursor")
            if not cursor:
                break
        return CollectionBatch(jobs=jobs, documents=documents, full_snapshot=True)
