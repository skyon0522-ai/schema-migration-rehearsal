# Schema migration recovery and compatibility rehearsal

Inspect and rehearse an interrupted enum addition without exposing the new label to a fixed older client. This example executes the actual copied Alembic `MigrationContext.autocommit_block`, adds `soso` to a synthetic PostgreSQL enum, and completes a separate marker transaction. A strict catalog/data check determines whether completion can resume. A table constraint keeps stored values inside the older client's accepted set until a separate, explicit activation.

## Observed example

The adapter passed with both the existing environment and a fresh environment built from 26 exact requirements pins. The fresh installed set also contained bootstrap pip 24.0, giving 27 observed distributions. Both runs used Python 3.12.3, existing PostgreSQL 18.6, SQLAlchemy 2.1.4 and psycopg2 2.9.13. The latest [functional receipt](verification/fresh/rollout-20261009T165704494174Z/contract-result.json) records all 11 scenarios and 17 worker exits. [VERIFICATION.md](VERIFICATION.md) separates the original/copy baseline, initial improvement, portable run and fresh acquisition/install/run evidence.

| Observation | Result |
| --- | --- |
| Kill worker before expansion | Fresh connection sees `sad, ok, happy` and no marker. |
| Kill worker after durable expansion, before marker commit | Fresh connection sees `sad, ok, happy, soso` and no marker; the worker exits -9. |
| Resume either interrupted case | Completes the marker; a second resume returns `already_complete` with equal full snapshots. |
| Read/insert/update with old labels while the gate remains | Succeeds; original ordered rows 1–3 remain unchanged and intentional client rows are retained. |
| Insert `soso` while the gate remains | Rejected with SQLSTATE `23514`, constraint `legacy_labels`; no rejected row remains. |
| Seven catalog, data or marker drift cases | Reject before copied autocommit executes; before/after snapshots are equal. |
| Explicitly activate, then use unchanged closed-set reader | Row 200 stores `soso`; the old reader rejects it. |

This demonstrates controlled worker termination and a specific client contract. It does not establish recovery from power loss. Alembic's copied autocommit block can commit a preceding transaction; the enum expansion and completion marker do not form an atomic rollback unit.

## Try the fixed contract

The unchanged adapter has executed successfully with the existing and freshly acquired environments. This convenient try route uses the 26 version pins. It is less strict than the observed fresh pipeline, which verified artifact hashes, built psycopg2 in a separate environment, and installed from its recorded wheelhouse with the index and automatic dependency resolution disabled.

Use Linux as a non-root user, Python **3.12.3**, and an existing PostgreSQL **18.6** installation containing `postgres`, `pg_ctl`, `initdb`, `createdb`, `psql` and `pg_config`. A C compiler, Python development headers and the matching libpq development files may be needed to build pinned psycopg2. These commands install dependencies only into a fresh task-local virtual environment. They do not install PostgreSQL.

From this repository, with the selected PostgreSQL `pg_config` on PATH:

```sh
SCHEMA_PG_BIN="$(pg_config --bindir)"
mkdir -p "$HOME/.cache"
SCHEMA_WORK="$(mktemp -d "$HOME/.cache/schema-migration-rehearsal.XXXXXXXX")"
python3 -m venv "$SCHEMA_WORK/venv"
PATH="$SCHEMA_PG_BIN:$PATH" "$SCHEMA_WORK/venv/bin/python" -m pip install -r requirements.lock
python3 -B tools/verify_source.py
python3 -B tools/run_contract.py \
  --python "$SCHEMA_WORK/venv/bin/python" \
  --pg-bin "$SCHEMA_PG_BIN" \
  --output-parent "$SCHEMA_WORK"
```

Replace `python3` if it selects a different version, and replace `--pg-bin` with an explicit PostgreSQL 18.6 directory when needed. The runner checks every dependency pin and executable version. Use an existing native Linux output directory outside the repository, rather than a Windows-mounted directory. The PostgreSQL shared-directory path must contain no whitespace, quotes, backslashes or commas because the retained harness uses a fixed startup option string.

The source check should report one 195-file source tree, eight protected rehearsal files, `status=source_verified` and `changed=[]`. The runner materializes two byte-identical source copies from that one staged tree inside a unique output directory, writes task-local metadata, and invokes the unchanged harness. That harness compares both source copies, creates only new loopback synthetic databases with trust authentication, preserves its receipts and logs, and stops its workers and cluster in `finally`. A successful receipt requires `all_stopped=true`, unchanged source trees and all scenario assertions. Run only this documented entry point; the imported upstream tree contains other tests and examples with their own assumptions.

The command above uses a version-only lock and may download build dependencies. It does not reproduce every control in the observed hash-checked acquisition/build/install pipeline. Bootstrap pip 24.0 was observed in both prepared environments and is outside the 26 pins; the adapter does not enforce its version. The [official-artifact hash lock](requirements.official-artifacts.hashed.lock) and [artifact metadata](verification/fresh/artifact-metadata.json) record the selected artifacts for the observed Linux x86_64 / CPython 3.12.3 profile. The lock is a proposal, not a tested standalone install recipe or a cross-platform bundle. The profile-specific driver wheel, local-built-wheel install lock and native tools are not distributed. No remote CI, bit-reproducible rebuild, different-machine run or fresh PostgreSQL installation is claimed.

## Root map

| Path | Purpose |
| --- | --- |
| [components/alembic](components/alembic) | Byte-identical 195-file package/test duplicate actually executed by the worker. |
| [rehearsal](rehearsal) | Four fixed SQL files, [copied-API worker](rehearsal/worker.py), [contract harness](rehearsal/check_contract.py), derivation receipt and retained MIT notice. |
| [tools](tools) | Source-only verifier and prepared task-local portability adapter. |
| [requirements.lock](requirements.lock) | 26 exact requirements pins, including upstream baseline test tools; observed bootstrap pip 24.0 is separate. |
| [requirements.official-artifacts.hashed.lock](requirements.official-artifacts.hashed.lock) | Proposed hashes for the 26 selected official artifacts, scoped to the observed profile. |
| [verification](verification) | Historical receipts, observations, dependency notices and independent review, with local path redactions. |
| [source-copy-manifest.json](source-copy-manifest.json) | Byte counts, SHA-256 values and Git blob identities for the complete copy; protected rehearsal hashes. |

[PROVENANCE.md](PROVENANCE.md) explains the copied implementation and limited SQL derivation. [VERIFICATION.md](VERIFICATION.md) describes the baseline, recovery scenarios, dependency acquisition and teardown. [RESEARCH.md](RESEARCH.md) maps the example to its inspected source behavior. [NOTICE](NOTICE), upstream [LICENSE](LICENSE) and [LICENSE.authored](LICENSE.authored) distinguish imported/derived material from task-authored coordination, documentation and adapters. [verification/redactions.json](verification/redactions.json) identifies sanitized evidence and original/public hashes.

## Scope

This is a fixed, single-coordinator example with a known schema, three original rows, an old-label client, a gate and one completion marker. `IF NOT EXISTS` is used only after strict expected-shape, label-order, row and marker checks; it is not a drift-hiding exception handler. Extra schemas/types/tables, reordered labels, altered original rows, a missing gate and a contradictory marker are rejected.

There is no enum removal, arbitrary concurrent schema writer handling, distributed rollout, zero-downtime claim, or production/security/customer-use guarantee. PostgreSQL 18 does not always require a nontransactional `ADD VALUE`; this example verifies the actual copied autocommit boundary. The explicit activation negative control shows when this older client becomes incompatible.

