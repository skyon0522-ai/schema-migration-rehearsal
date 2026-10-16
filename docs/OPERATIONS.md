# Linux operation walkthrough

Use this example to learn one interrupted enum change, compare the two durability
boundaries, and see why old-client compatibility ends at activation. It is a
fixed synthetic rehearsal. It accepts no database URL or arbitrary migration.

## First use

Clone or unpack the checkout on Linux. Use a non-root x86_64 account and an
existing CPython **3.12.3** with venv/pip **24.0**, Python development headers,
C compiler, and complete PostgreSQL **18.6** installation. The exact prerequisites
and a separate source-build recipe are in [LINUX.md](LINUX.md). The wrapper
checks these prerequisites; it does not install system packages or services.

From the checkout, choose a new work parent on native Linux storage outside
the checkout and `/mnt`. Replace the PostgreSQL example with its actual bin path.

```sh
mkdir "$HOME/schema-demo"
bash examples/linux-demo.sh /usr/bin/python3.12 \
  "$HOME/.local/opt/postgresql-18.6/bin" "$HOME/schema-demo"
```

The script follows the existing doctor → prepare → run → report commands. It
prepares `schema-demo/environment` only when absent. Preparation downloads the
26 recorded official artifacts, checks their sizes and SHA-256 values, builds
psycopg2 against the selected libpq, and installs a fresh hash-locked runtime.
No pip cache, index, dependency resolution or global Python install is used.
If preparation fails, preserve its receipt/logs, correct the prerequisite and
choose a new work parent; the script never overwrites a partial environment.

The final run JSON prints two distinct paths:

| Field | Meaning |
| --- | --- |
| `run_parent` | Exclusive `schema-run-xxxxxxxx` directory; exact target for cleanup |
| `run` | Child `schema-migration-...` directory containing the saved evidence |
| `report` / `summary` | Generated offline HTML and plain-text report |

The script prints a terminal summary after the JSON. Successful output starts:

```text
Schema Migration Rehearsal: consistent_record
11 scenarios; 17 worker exits; recorded cluster and worker cleanup passed.
Expected controls: 2 SIGKILL exits, 7 drift rejections, 1 old-reader incompatibility.
```

`consistent_record` means the saved records satisfy the fixed evidence checks.
It is not a current database-health probe, an authenticated attestation or a
production-readiness result. The two SIGKILL exits, drift rejections and final
old-reader failure are required controls; changing them into successes fails
inspection. [The committed example](../examples/current/summary.txt) shows all
11 scenario outcomes without requiring PostgreSQL or a browser.

## Inspect and repeat

Copy the exact `run` field printed by your invocation into `SCHEMA_RUN`:

```sh
SCHEMA_RUN=/absolute/path/from/the/run/field
python3.12 -B tools/report.py --run "$SCHEMA_RUN"
python3.12 -B tools/report.py --run "$SCHEMA_RUN" --json
```

Both commands are read-only and return `0` only for complete consistent evidence.
Missing, changed or contradictory records return `1` and identify the stage
that failed. They create no database, worker or report directory. To create a
separate report copy, add `--output /new/absent/report-directory`; it writes
`report.html`, `review.json` and `summary.txt`, and refuses existing output.

Run the same `linux-demo.sh` command again to verify a separate rehearsal. The
prepared dependency environment is reused and checked again; its packages are
not reinstalled. Each rehearsal gets a new exclusive run directory and starts
the adapter exactly once. A repeat is a new synthetic rehearsal, not a resume
of a previously running production migration. Resume/idempotence observations
are the two internal interruption scenarios in each fixed rehearsal.

## Diagnose a failure

| Symptom | Action |
| --- | --- |
| PostgreSQL bin directory unavailable | Set the actual complete 18.6 installation path; selecting an empty directory is insufficient. |
| Python profile/header/compiler check failed | Select CPython 3.12.3 and matching development headers; use `--cc` with the individual doctor/prepare commands for an explicit compiler. |
| Existing preparation directory refused / invalid receipt | Preserve the failed directory and its logs; select a new absent environment/work parent. |
| Download, size or SHA-256 check failed | Inspect the recorded URL, error and `.partial` file. Correct access or artifact availability before a new preparation; the tool does not retry or accept another artifact. |
| Runtime packages changed | Preserve the environment for diagnosis and prepare a new one. The tool does not repair it silently. |
| Run failed | Read `run-wrapper.json`, `adapter.stderr.log`, then the child `harness.stderr.log` and `project/evidence/rollout-...` records. A failed or missing receipt is never an overall pass. |
| Saved result incomplete or inconsistent | Use `failure_stage` from `--json`; retain original evidence. Do not edit raw records to turn a failure into a pass. |

The sandbox returns `2` for invalid/unavailable input, `1` for a recorded setup
or rehearsal failure, and `0` for success. The report returns `1` for incomplete
evidence and `2` when requested output cannot be safely created. `doctor` is
read-only and checks no network access. Failed preparation/run outputs are kept.

## Retain evidence and clean up one stopped run

Archive the report and any needed raw evidence before removal. Reports omit raw
machine paths, while raw receipts/logs can contain them. Inspect all files before
sharing. The original raw evidence is needed to rerun the full offline checker;
the three report files alone are a readable saved result.

Copy the exact **`run_parent`** field into `SCHEMA_RUN_PARENT`. Review the path
and preserve the evidence you need. Then inspect and explicitly remove that run:

```sh
SCHEMA_RUN_PARENT=/absolute/path/to/schema-run-xxxxxxxx
python3.12 -B tools/sandbox.py cleanup --run-parent "$SCHEMA_RUN_PARENT"
python3.12 -B tools/sandbox.py cleanup --run-parent "$SCHEMA_RUN_PARENT" --remove
```

Cleanup checks the resolved native path, exact run-directory pattern, matching
ownership/wrapper records and recognized top-level contents. It refuses symlinks,
unrecognized roots, prepared environments, parent directories and any remaining
`postmaster.pid`. An unreadable directory makes inspection incomplete and refuses
cleanup before any files are removed. Without `--remove` it only reports
`cleanup_ready`. The local
ownership token helps avoid accidental selection; editable local records are
not authentication. Removal never signals a process and never deletes the
prepared environment, PostgreSQL installation or another run.

The rehearsal normally stops its own cluster and workers before returning. If
`postmaster.pid` remains, keep the directory and inspect the exact owned cluster
from its receipt/logs; do not use a broad process kill or delete a running cluster.
Older runs without the new ownership record are intentionally refused. Prepared
environments remain available for later runs; this cleanup command does not
remove them or manage a system service.

## Reference and limits

The commands reuse `tools/sandbox.py`, `tools/run_contract.py`, `tools/report.py`
and their existing exclusive-workspace and evidence-validation behavior. The
underlying Alembic example is
[`PGAutocommitBlockTest.test_alter_enum`](../components/alembic/tests/test_postgresql.py)
and [`MigrationContext.autocommit_block`](../components/alembic/alembic/runtime/migration.py),
including its documented commit boundary. These copied sources and all protected
SQL/worker/harness files remain unchanged. New operation helpers do not add
arbitrary migrations, concurrent schema writers, a distributed rollout protocol,
power-loss recovery or zero-downtime guarantees. See [PROVENANCE.md](../PROVENANCE.md)
for the pinned source and licenses, and [RESEARCH.md](../RESEARCH.md) for research
connections and boundaries.
