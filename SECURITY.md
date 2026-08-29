# Security policy

Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/AryanPaneru12/nepal-tech-jobs-data/security/advisories/new).
Do not include secrets or raw private source data in a public issue.

Collectors reject non-public IP destinations, credential-bearing URLs, unchecked redirects, and oversized
responses. API keys belong in environment variables or GitHub Actions secrets. Raw crawl objects must be
stored in a private bucket with lifecycle policies matching the source catalog.
