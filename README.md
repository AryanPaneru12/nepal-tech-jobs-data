# Nepal Tech Jobs Data

[![CI](https://github.com/AryanPaneru12/nepal-tech-jobs-data/actions/workflows/ci.yml/badge.svg)](https://github.com/AryanPaneru12/nepal-tech-jobs-data/actions/workflows/ci.yml)
[![Weekly data refresh](https://github.com/AryanPaneru12/nepal-tech-jobs-data/actions/workflows/weekly-data.yml/badge.svg)](https://github.com/AryanPaneru12/nepal-tech-jobs-data/actions/workflows/weekly-data.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Code license: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-blue.svg)](LICENSE)
[![Data license: ODC-BY-1.0](https://img.shields.io/badge/data-ODC--BY--1.0-green.svg)](DATA_LICENSE.md)

An evidence-first, open-source data pipeline for:

1. technology employers based in or operating in Nepal; and
2. technology and adjacent jobs that a Nepal-based applicant may be able to perform.

The project favors traceability over unsupported claims. A remote job is never silently presented as
Nepal-eligible: every job has an `eligible`, `likely`, `unknown`, or internal `ineligible` assessment,
the evidence that triggered it, a confidence score, and a rule version.

## What v1 contains

- A typed source-policy catalog and pluggable collector interface.
- Safe HTTP collection with host throttling, robots checks for web pages, bounded responses, retries,
  redirect validation, and private-network/SSRF rejection.
- Public ATS adapters for Greenhouse, Lever, and Ashby.
- Remote feed adapters for Himalayas, Remote OK, and Remotive.
- Brave Search discovery and Google Places ID-only discovery adapters, disabled until credentials and
  source review are supplied.
- Manual CSV import for registry data that cannot be collected without CAPTCHA or access controls.
- DuckDB normalization, entity resolution, cross-source job deduplication, evidence lineage, review
  queues, and two-successful-snapshot closure rules.
- CSV, JSONL, Parquet, and public DuckDB exports with checksums, attribution, coverage, and schema docs.
- Weekly GitHub Actions updates through a generated review pull request.

This is not a job application bot, web interface, or RAG implementation. The records and provenance are
structured so those systems can be built later.

## Dataset

The latest public snapshot is available directly in [`data/current`](data/current). It contains:

| Artifact | Purpose |
| --- | --- |
| `companies.*` | Canonical employer identities and Nepal relationships |
| `jobs.*` | Active, publishable technology and adjacent roles |
| `evidence.*` | Field-level provenance, confidence, hashes, and attribution |
| `runs.*` | Auditable ingestion history and source health |
| `nepal_jobs_public.duckdb` | Query-ready combined database |
| `manifest.json` | File sizes and SHA-256 checksums |

See the generated [coverage report](data/current/COVERAGE.md), [data dictionary](data/current/DATA_DICTIONARY.md),
and [source attribution](data/current/ATTRIBUTION.md). Counts are snapshots, not claims of complete labor-market coverage.

## Quick start

Install [uv](https://docs.astral.sh/uv/), then run:

```bash
uv sync --extra dev
uv run njobs sources check
uv run njobs sources list
uv run njobs collect --source remotive --dry-run
uv run njobs run weekly
uv run njobs validate
uv run njobs export --format csv
uv run njobs stats
```

`uv` provisions the Python 3.12 interpreter declared in `.python-version` when it is not already
installed. Runtime output defaults to `data/work` and `data/private`, both ignored by Git.

## Live progress and logs

Collection commands print every source, HTTP request, retry, rate-limit wait, archive batch, and
normalization milestone as it happens. Each line is flushed immediately, so a long source does not look
stuck:

```text
[10:14:02] weekly_source_started position=1 source=himalayas total=3
[10:14:02] fetch_started method=GET request=1 source=himalayas url=https://...
[10:14:03] fetch_completed bytes=82410 elapsed_seconds=0.84 request=1 status=200
[10:14:03] rate_limit_wait host=himalayas.app wait_seconds=5.13
[10:25:47] jobs_progress processed=1000 retained=438 skipped_non_tech=121 total=2140
```

The same events are saved as structured JSON Lines files under `data/logs/`. The first terminal line
shows the exact log path. To follow the newest log from a second Git Bash window:

```bash
latest=$(ls -t data/logs/*.jsonl | head -1)
tail -f "$latest"
```

Press `Ctrl+C` to stop following the log; this does not stop the collector running in the other window.
Logs start with the next command invocation—code updates cannot attach logging retroactively to a
process that was already running.

For a release candidate, run `uv run njobs validate --release`. This additionally enforces the agreed
minimums of 500 relevant companies and 2,000 active publishable jobs. The repository does not ship
fabricated seed records merely to satisfy those numbers.

## Pipeline stages

```text
discover -> fetch -> archive -> parse -> normalize -> resolve -> classify -> validate -> export
```

- Discovery results are leads, not verified companies.
- Raw HTTP bodies are compressed and private. Configure R2 to move them out of the local runtime.
- Parsers produce typed candidates; invalid upstream records fail visibly.
- Company domains are authoritative merge keys. Conservative fuzzy name matches are queued for review.
- Job fingerprints combine employer, normalized title, and location. First-party ATS evidence outranks
  aggregator copies.
- Explicitly ineligible roles are kept only as internal audit items and never enter active public exports.
- A job absent from one successful full snapshot remains active; two consecutive successful absences
  close it. An empty or failed source run never closes every job.

## Repository layout

```text
config/sources/       Declarative source policy and connector configuration
data/current/         Versioned public release artifacts
src/nepal_jobs/       Collectors, normalization, resolution, validation, and CLI
tests/                Unit, contract, safety, and golden-fixture tests
.github/workflows/    CI and weekly data-refresh automation
```

`main` is the reviewed, release-ready branch. `develop` is the integration branch for parser and pipeline
work. Automated data refreshes open reviewable pull requests against `main` from `data/weekly-refresh`.

## Source policies

Every adapter has a YAML file in `config/sources`. A source cannot be enabled without an reviewed access
mode and redistribution decision. Important fields include:

- `access_mode`: `api`, `feed`, `html`, `search`, `manual`, or `blocked`;
- `obey_robots`, request rate, attribution, terms URL, and raw retention;
- `redistribution`: `facts_only`, `attributed`, `restricted`, or `unknown`;
- full-snapshot and refresh semantics; and
- connector-specific parameters such as ATS board tokens.

To add a Greenhouse employer, add an item under `parameters.boards` and enable the source:

```yaml
parameters:
  boards:
    - token: example
      company: Example, Inc.
      website: https://example.com
```

Never enable a source merely because a parser can technically retrieve it. Record its terms, attribution,
rate limit, retention, and publication policy first. Do not bypass login, CAPTCHA, paywalls, or anti-bot
controls. OCR registry data therefore uses a human-provided export rather than automating its challenge.

## Manual Nepal company import

Create `data/imports/ocr_companies.csv` with this header:

```csv
name,legal_name,registration_id,website,careers_url,sectors,country,locality,address,nepal_relationship,email,phone,profile,confidence,source_url
```

Use `|` between multiple sectors. Only organization-level contact details are allowed. After reviewing
the data and source policy, enable `ocr_manual` and run:

```bash
uv run njobs collect --source ocr_manual --run-id ocr-approved-2026-08
```

## Private raw storage

Without cloud credentials, raw artifacts are written beneath `data/private/raw`. For Cloudflare R2 or
another S3-compatible store, set these secrets (never commit them):

```text
R2_ENDPOINT_URL
R2_BUCKET
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
```

The archive stores compressed source responses and metadata. Public exports include only content hashes
and storage-safe provenance, never storage credentials or raw object pointers.

## Public data and review flow

`njobs export` writes to `data/current` by default. Public job exports deliberately omit full descriptions;
they contain facts, short evidence, source and application URLs, timestamps, confidence, and attribution.

```bash
uv run njobs review export
uv run njobs export --format csv
uv run njobs export --format jsonl
uv run njobs export --format parquet
uv run njobs export --format duckdb
```

The weekly workflow updates sources, validates the database, exports data, and opens a pull request. The
pull request is the publication gate: a maintainer reviews additions, closures, source failures, unusual
count changes, duplicate candidates, and the pending review queue before merging.

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest --cov=nepal_jobs
```

Golden fixtures are sanitized and contain no copied full descriptions. Live source responses are never
committed as test fixtures.

## Roadmap

- Expand verified Nepal company directories and first-party careers-page coverage.
- Add source-reviewed ATS connectors and improve closure monitoring.
- Publish labeled evaluation sets for role scope, entity matching, and Nepal eligibility.
- Add a search/API layer after the dataset meets its quality and coverage release gates.
- Prepare permission-aware chunks for future RAG applications without publishing restricted text.

See [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a source or parser. This project provides discovery
data, not employment guarantees or legal advice; applicants must verify role eligibility with the employer.

## Licensing

Code is Apache-2.0. Original curated database content is ODC-BY-1.0. Upstream restrictions still apply;
see `DATA_LICENSE.md` and the generated attribution catalog. ODbL data must remain in a separate export.
