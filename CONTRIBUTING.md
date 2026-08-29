# Contributing

Contributions are welcome for source policy reviews, parser fixtures, taxonomy rules, entity corrections,
and documentation.

## Branch and pull-request flow

1. Branch from `develop` using `feature/<short-name>`, `fix/<short-name>`, or `source/<source-id>`.
2. Keep source-policy changes separate from generated data changes when practical.
3. Run `uv run ruff check .`, `uv run pytest`, and `uv run njobs sources check`.
4. Open a pull request into `develop`. Release and automated reviewed-data pull requests target `main`.
5. Describe source terms, redistribution limits, fixtures, and expected record-count changes.

For a new source:

1. document ownership, terms, access mode, rate limit, attribution, retention, and redistribution;
2. prefer a public API or feed over HTML collection;
3. add a sanitized parser fixture and contract tests;
4. prove that failure or an empty response cannot close existing jobs;
5. keep personal recruiter details and restricted content out of exports; and
6. leave the source disabled until a maintainer verifies the policy and parser.

Do not submit CAPTCHA bypasses, credential sharing, proxy evasion, or automated application features.
