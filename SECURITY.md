# Security and local-data boundaries

This is a disposable local demonstration. It accepts no database URL and must
not be pointed at a production data directory. The retained harness creates a
new PostgreSQL cluster on loopback with trust authentication for synthetic data.
Do not expose it beyond the local machine or use it on a shared untrusted host.

Preparation runs the fixed, hash-checked native driver build and installed
dependencies with your account's permissions. A hash identifies the selected
artifact; it does not establish that the dependency is free of vulnerabilities.
Use a dedicated Linux account or disposable development environment when that
matches your data boundary. No command installs a system service or requests
superuser access; the GitHub workflow's prerequisite installation occurs only
on its disposable runner.

Raw setup/run records may contain local filesystem paths and connection
details. Inspect them before sharing. The portable HTML/JSON report exports
only selected fixed-contract outcomes and hashes. Saved evidence is editable;
its validation does not authenticate the author or establish current database
health. Stable owner-controlled files are required.

For ordinary reproducible bugs, use
[GitHub Issues](https://github.com/skyon0522-ai/schema-migration-rehearsal/issues)
with the commit, runtime versions and sanitized error. For a suspected security
issue, request a private reporting channel there without publishing exploit
details, credentials, real database contents or raw logs. A private reporting
channel and response time are not promised until confirmed.
