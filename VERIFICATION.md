# Verification and scope

## Linux preparation and result screen: 2026-10-15

The unchanged pinned base at `4f602a38f578efd433fb2a3f6dfbab963033f091` passed in a new native directory using the existing accepted environment. The new preparation command then acquired all 26 selected official artifacts, built psycopg2 in a separate environment and installed the exact runtime from a local hash-checked wheelhouse. The complete profile contained the 26 pins plus bootstrap pip 24.0; the build environment contained only pip 24.0 and setuptools 84.0.0. The actual wrapper invoked the unchanged adapter once and passed all 11 scenarios with 17 worker exits.

A separate new PostgreSQL 18.6 installation was built from the official 22,632,314-byte archive with SHA-256 `555610c24d53e4316da5b7d3fc25c279d96856d5e0e23ee308c328c5fa881d9f`. It used a new native VPATH build, an owned prefix, `--without-icu --without-readline`, `make -j2 all` and `make install`. Existing task-local Bison/Flex/m4 tools supplied build prerequisites; no system packages or existing PostgreSQL installation were changed. This source build did not run the upstream PostgreSQL regression suite.

A second clean dependency preparation built the driver against that new installation. Compiled and loaded libpq both reported 180006. The subsequent single adapter invocation again passed 11 scenarios and 17 worker exits, with empty fallback cleanup. Both materialized 195-file Alembic trees and all eight protected rehearsal files remained unchanged. After all three observed runs, no owned application processes remained and each recorded listener refused connection. These are observations on the existing Ubuntu 24.04/WSL2 OS, not a new-machine or fresh-OS result.

All 47 focused tests passed: 17 preparation/wrapper boundary tests and 30 saved-record/report tests. The latter use disposable copies of actual records and check missing worker files, changed source/SQL, contradictory interruption states, altered repeated-resume data, empty command lists and other false-pass cases. A report requires consistency with the 17 raw worker records and expected scenario/exit/cleanup fields; it does not reconnect to PostgreSQL or authenticate the records. The read-only doctor created no task state. Missing prerequisites, mounted output and existing preparation directories were rejected without overwriting the existing environment receipt.

The generated screen matched 11 scenario rows, two interruption rows and four evidence checks to its JSON on desktop and mobile. Keyboard scrolling/details, local links and print styles were checked with no external requests. The [portable example](examples/current/report.html), [review JSON](examples/current/review.json) and [compact observation record](verification/linux-20261015.json) omit raw connection details and machine paths. Raw logs, local wheelhouse/install locks and native binaries remain private; hashes commit to those observed bytes and are not a distributed rebuild package or authentication.

The new [Linux workflow](.github/workflows/linux.yml) follows the observed source-build/preparation/run path and passed actionlint 1.7.12 plus shell/Python syntax checks. GitHub Actions execution was **UNRUN** at this pre-publication local review stage. The initial Linux GitHub Actions fixed migration rehearsal run later passed for published commit [`fd31b227cac3edb72783d6a88674b56d5db5d1a5`](https://github.com/skyon0522-ai/schema-migration-rehearsal/commit/fd31b227cac3edb72783d6a88674b56d5db5d1a5) on 2026-10-16 (run [`38848337437`](https://github.com/skyon0522-ai/schema-migration-rehearsal/actions/runs/38848337437)). This result applies to that published commit. Other machines, runtime versions, distributions, reproducible binary bytes and production suitability are unverified.

## Earlier retained observations: 2026-10-09

The following historical sections describe the source, commands and remaining work as recorded on that date. In particular, their version-only convenience route and unperformed PostgreSQL installation statements are historical; the current route and new observations are documented above and in the [Linux guide](docs/LINUX.md).

The original/copy baseline, initial improvement, existing-environment adapter run and fresh-acquisition adapter run are observed evidence. The code retained here matches the executed source.

### Original and unchanged-copy baseline

Both complete Alembic trees ran `tests/test_postgresql.py::PGAutocommitBlockTest::test_alter_enum` with Python 3.12.3, PostgreSQL 18.6, SQLAlchemy 2.1.4, psycopg2 2.9.13 and the same remaining dependency pins. The two template0 databases used one fresh loopback-only synthetic cluster. Original: one passed, exit 0, 0.59 seconds. Duplicate: one passed, exit 0, 0.55 seconds.

The successful [baseline receipt](verification/baseline/baseline-20261009T152911062556Z.json) has timestamp `2026-10-09T15:29:11.070422+00:00`. External observations from [original](verification/baseline/20261009T152911062556Z-original-observation.json) and [duplicate](verification/baseline/20261009T152911062556Z-duplicate-observation.json) read `sad, ok, happy` before the body, `sad, ok, happy, soso` before teardown, then no remaining type after teardown. Runtime frames resolved to the selected source tree. The copied DDL used DBAPI autocommit true, with transaction status 0.

Three earlier attempts remain visible: [long socket path](verification/baseline/baseline-20261009T152041000712Z.json), [missing libpq loader path](verification/baseline/baseline-20261009T152153317939Z.json), and [missing contrib extensions](verification/baseline/baseline-20261009T152339414371Z.json). Their separate fixes were TCP-only sockets, scoped library search and task-local verified contrib builds. None is presented as a passed run. All four attempt clusters ended stopped.

### Accepted improvement

The [functional receipt](verification/rollout-20261009T154922160131Z/contract-result.json), timestamp `2026-10-09T15:49:22.167802+00:00`, contains all 11 completed scenarios and 17 worker exits. Its original private SHA-256 is `ded5dedbb5227fda195cb7d11d59736e35835cd751900ea2dc88ad6ac00a451c`; the staged version has local-path redactions and a separate hash in [redactions.json](verification/redactions.json). The four SQL files, worker and harness bodies are unchanged from that accepted run.

| Scenario | Evidence interpretation |
| --- | --- |
| `normal_and_old_clients` | Original IDs 1–3 remain ordered and unchanged. Old-label insert/update succeeds; premature new-label write is rejected with `23514`/`legacy_labels`. Repeated completion leaves full snapshots equal. |
| `stop_before_expansion` | Separate worker reaches its barrier, is killed with SIGKILL/-9, and fresh connection retains old labels and no marker. Resume completes; another resume has no effects. |
| `stop_after_durable_expansion` | Worker has inserted its uncommitted marker; an independent connection sees `soso` and no marker. SIGKILL/-9 leaves that observed durable expansion. Resume completes; another resume has no effects. Old client operations remain valid while the gate is present. |
| `wrong_schema`, `wrong_type`, `wrong_table`, `wrong_gate`, `contradictory_marker`, `changed_original_row`, `wrong_label_order` | Each worker rejects before source execution, with empty events and equal before/after state. The renamed-schema rows are also compared. |
| `activation_negative_control` | Explicit gate removal permits row 200 with `soso`; the same unchanged closed-set reader reports `Old reader rejects stored label 'soso' at row 200`. |

Five worker records contain actual copied `autocommit_block` frames and autocommit DDL. Every original/duplicate source hash still matches the 195-file manifest. All 17 workers stopped, `pg_ctl status` returned 3, the pid file was absent, and port 40431 was closed.

The [independent review](verification/independent-review.md) returned `PASS_WITH_SCOPE_LIMITS`. It inspected code, receipts, hashes and stopped state without rerunning the suite. Its read-only probe at `2026-10-09T16:01:50Z` found pg_ctl status 3, no postmaster.pid, closed port 40431 and none of the 17 recorded worker PIDs. Its verdict is an evidence review, not publication approval.

### Portable and fresh-environment runs

The [existing-environment adapter receipt](verification/portable-existing/portable-run.json) and its [functional receipt](verification/portable-existing/rollout-20261009T164456855513Z/contract-result.json) both passed. Adapter/harness exit codes were 0; all 11 scenarios and 17 worker exits completed. The original private functional SHA-256 is `b88ff614465beac2af0281a4d7f2919752597f6067751196e113ba6805c847bd`. The live probe at `2026-10-09T16:47:04.633128+00:00` returned pg_ctl 3, no pid, closed port 53869 and no recorded workers/PostgreSQL process. Both materialized 195-file trees, all eight rehearsal files and all 360 then-staged files matched their recorded hashes.

Fresh acquisition is recorded in the [fresh review receipt](verification/fresh/review.json) and [artifact metadata](verification/fresh/artifact-metadata.json). All 26 exact pins were newly downloaded from official PyPI: 25 wheels and psycopg2 2.9.13 source, each matching the published size/SHA-256. A separate build venv contained only pip 24.0 and setuptools 84.0.0. The source declared only setuptools≥70.1; no additional build-only distribution was installed. GCC was `13.3.0-6ubuntu2~24.04.1`; existing PostgreSQL/libpq 18.6 provided headers/libraries. Driver compile/runtime libpq was 180006.

The runtime install used a fresh wheelhouse with `--no-index --no-deps --no-cache-dir --only-binary=:all: --require-hashes`. Installed metadata exactly matched 26 requirements pins plus observed bootstrap pip 24.0, with no unexpected additions; pip check passed. The [proposed official-artifact lock](requirements.official-artifacts.hashed.lock) records the selected artifacts. The actually used local runtime-wheel lock and built driver wheel are not distributed; the [build evidence](verification/fresh/artifact-metadata.json) labels their CPython 3.12/Linux x86_64/libpq 18.6 profile. A separate offline reinstall/rebuild was not performed.

The [fresh adapter receipt](verification/fresh/portable-run.json) and [fresh functional receipt](verification/fresh/rollout-20261009T165704494174Z/contract-result.json) passed with exit 0 and all 11 scenarios/17 worker exits. Their original private SHA-256 values are respectively `d3229d79792c5f17501d58cb49023d874331b93aaaf725564f35a11208bb0555` and `d71a689e06bcffad867968cc78f89b61e4632a6c7cf9f9afc88c26e5fb2a08dd`. Five worker records again contain copied autocommit frames and autocommit DDL. Both materialized sources and protected rehearsal bytes matched; fresh connection interruption/resume/readbacks, row retention, old-client gate, seven drift cases and activation control all passed. At `2026-10-09T16:58:46.903708+00:00`, pg_ctl returned 3, the pid was absent, port 60687 was closed and no recorded PostgreSQL or 17 worker PIDs remained. Adapter fallback cleanup was empty; stage and recorded PostgreSQL binary hashes stayed unchanged.

### Source and evidence checks

The checks cover full source/rehearsal byte identity, retained notices, source-verifier output, Python syntax without importing the runtime, authored Markdown local-link existence, sanitized-evidence equivalence and a complete file allowlist with SHA-256 values. [publication-file-manifest.json](publication-file-manifest.json) records the distribution files and excludes its own entry to avoid a self-hash cycle.

The convenient try command uses 26 version pins and a new venv; observed pip 24.0 is separate bootstrap metadata. This convenience route is not the exact verified hash-controlled acquisition/build/install sequence and may resolve build dependencies. Both adapter execution and fresh dependency acquisition are now observed for the documented Linux x86_64/Python 3.12.3/existing PostgreSQL 18.6 profile. The unchanged adapter injects only metadata into an external working copy and selects the existing PostgreSQL shared directory; this harness creates no extensions.

The distribution contains source, notices, artifact metadata and the proposed official-artifact hash lock. No native executables, dependency wheels, environments or caches are distributed; the unchanged upstream documentation PNG is retained as a manifest-bound source asset. The local-built-wheel install lock is not distributed. Root LICENSE remains upstream MIT; LICENSE.authored supplies MIT for authored coordination, documentation and adapters. [Redaction metadata](verification/redactions.json) records original and sanitized hashes while preserving observations. At the time of these earlier local checks, remote CI, a different-machine run, a bit-reproducible build and fresh PostgreSQL installation had not been performed.

### Limits preserved

The result applies only to this fixed single-coordinator client/data contract. Controlled worker termination is not power-loss testing. Copied autocommit may commit preceding work, and the enum addition cannot be removed by this example. No arbitrary concurrent schema writers, distributed rollout, zero-downtime behavior, production/security suitability or customer use is established. Explicit activation is deliberately incompatible with the unchanged old reader.
# Linux operation finish — 2026-10-16

The new operation path was exercised from a new native checkout/work directory
on the existing Ubuntu 24.04 WSL host. CPython 3.12.3 and the previously verified
task-local PostgreSQL 18.6 installation were reused. This was a fresh application
installation, not a fresh OS or new PostgreSQL build. `prepare` downloaded the
26 selected official artifacts into new directories with pip caches disabled,
verified their recorded sizes/hashes, built psycopg2 in a new build environment,
and installed a new runtime. Compiled/runtime libpq was 180006.

The documented `bash examples/linux-demo.sh PYTHON PG_BIN WORK_PARENT` command
passed on first use and again with the same arguments. Each invocation ran the
unchanged adapter once and completed 11 scenarios and 17 worker exits. The
repeat created a distinct run and left `environment.json`, the runtime hash lock
and `install-report.json` byte-identical; it did not reinstall dependencies.
The second run's raw evidence remains available privately for consolidated
review. Its generated text/JSON inspection passed without creating new output.

All **53** standard-library safety, corruption and operation tests passed with
`SCHEMA_RECORDED_RUN` set to that actual second run. New operation tests cover
read-only failed inspection, explicit removal, refusal of parent/environment
targets, changed ownership, foreign contents, symlinks and a remaining
`postmaster.pid`. Separate CLI negative checks rejected a missing PostgreSQL
directory, mounted output, a work-parent cleanup target and a prepared-environment
cleanup target with exit 2. The documented shell example passed `bash -n`.

The first stopped run was inspected and then removed through the explicit
`cleanup --run-parent EXACT_RUN --remove` command after its acceptance records
and reports were preserved outside it. The second run and prepared environment
remained present. No unrelated process was signalled, and no system service,
package or global configuration was changed. Cleanup markers protect against
accidental selection; they do not authenticate local editable files. A remaining
PID file or unrecognized contents are conservative refusal conditions.

Source verification before and after the runs confirmed all **195** imported
Alembic files and **8** protected rehearsal files unchanged. The contract adapter
also remains byte-identical to the prior staged candidate. The exact public
profile, operation commands and limits are in
[`verification/operations-20261016.json`](verification/operations-20261016.json)
and [the walkthrough](docs/OPERATIONS.md). Private command logs and machine paths
are kept outside the public candidate. At this local operation-verification stage, different-machine execution, remote CI,
production use, publication and owner acceptance had not yet occurred. The subsequent publication and initial CI success are recorded above.

### Cleanup traversal repair

Independent review reproduced an unreadable nested directory being skipped by
`os.walk`, which could let removal delete the wrapper records and logs before
failing. Cleanup now raises on any traversal error before reaching removal.
The new regression uses a real nested directory with mode `000` containing
`postmaster.pid` and a binary evidence file. Both inspection and explicit removal
are refused, and every original file name and byte is retained after refusal.

After this repair, all **7** operation tests and the full **54**-test saved-record,
safety and operation suite passed as a non-root Linux user, with no skipped tests.
The 53-test result above remains the earlier acceptance history. The existing
second run supplied saved records; no installation or database rehearsal was
repeated. All 195 imported Alembic files, eight protected rehearsal files,
dependency pins and the adapter remained unchanged. The repair does not provide
atomic protection against concurrent filesystem changes. Independent closure of
the finding and owner acceptance remain pending.

