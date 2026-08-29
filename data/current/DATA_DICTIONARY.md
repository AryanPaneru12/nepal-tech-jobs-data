# Data dictionary

## companies

Canonical employer identity, Nepal relationship, verified organization channels, confidence, and provenance.
JSON-valued fields such as aliases and sectors are serialized as JSON strings in CSV exports.

## jobs

Active technology and adjacent jobs. `eligibility` is `eligible`, `likely`, or `unknown`; explicitly
ineligible jobs are excluded. Evidence and rule version explain the classification. Full descriptions
are intentionally excluded from public exports.

## evidence

Record-level provenance with source URL, observation timestamp, short permitted snippet, parser version,
content hash where available, confidence, and attribution.

## runs

Public ingestion-run summaries used to audit freshness and source failures. Private error details and raw
storage pointers are excluded.
