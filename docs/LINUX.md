# Prepare and run the recorded Linux profile

For the shortest first-use, inspect, repeat and cleanup path, follow
[the operation walkthrough](OPERATIONS.md). This guide explains the exact
dependency preparation and optional native prerequisite build.

This route acquires and verifies the 26 selected official artifacts, builds the
pinned driver in a separate virtual environment, and prepares a fresh runtime.
It uses the existing `tools/run_contract.py` and protected rehearsal unchanged.
The implementation follows the recorded commands in
[`verification/fresh/review.json`](../verification/fresh/review.json), the exact
URLs and SHA-256 values in
[`artifact-metadata.json`](../verification/fresh/artifact-metadata.json), and the
exclusive-workspace/read-only-preflight pattern inspected in OTel Incident
Sandbox's `tools/sandbox.py`.

## Existing prerequisites

Use a **non-root Linux x86_64** account with **glibc 2.17 or newer**, an existing
**CPython 3.12.3** installation with `venv`, bundled **pip 24.0**, its development
headers, a C compiler, and an existing complete **PostgreSQL 18.6** installation.
The selected PostgreSQL directory must contain `postgres`, `pg_ctl`, `initdb`,
`createdb`, `psql` and `pg_config`, plus its matching libpq headers, shared
library and initdb data. Every executable's version is checked. PostgreSQL's
shared-data path must contain no whitespace, quotes, backslashes or commas,
because the retained harness constructs a fixed startup-option string.

Install prerequisites separately using the installation procedure appropriate
for your Linux distribution. PostgreSQL's official
[source installation guide](https://www.postgresql.org/docs/18/installation.html)
and [build prerequisites](https://www.postgresql.org/docs/18/install-requirements.html)
describe the native tools and libraries. Python's official
[venv documentation](https://docs.python.org/3.12/library/venv.html) describes
virtual environments. `tools/sandbox.py` does not install PostgreSQL, change
system packages, call `sudo`, or manage a system service. The application wrapper
requires an explicit existing PostgreSQL installation. The optional source-build
recipe below was also executed in a new native directory on the same Linux host.
A different machine and the remote GitHub Actions job remain unverified.

## Check, prepare, run

Run these commands from the checkout. Replace the PostgreSQL example with the
explicit path to your existing installation. `SCHEMA_ENV` must name a directory
that does **not** exist; its parent must already exist. Use a native Linux
filesystem outside the checkout and `/mnt`; output paths containing symlinks are
rejected. Preparation never overwrites or resumes an existing directory.

```sh
SCHEMA_PYTHON=/usr/bin/python3.12
SCHEMA_PG_BIN="$HOME/.local/opt/postgresql-18.6/bin"
SCHEMA_ENV="$HOME/schema-migration-environment"

"$SCHEMA_PYTHON" -B tools/sandbox.py doctor \
  --python "$SCHEMA_PYTHON" --pg-bin "$SCHEMA_PG_BIN" \
  --output-parent "$HOME"

"$SCHEMA_PYTHON" -B tools/sandbox.py prepare \
  --python "$SCHEMA_PYTHON" --pg-bin "$SCHEMA_PG_BIN" \
  --work-dir "$SCHEMA_ENV"

"$SCHEMA_PYTHON" -B tools/sandbox.py run \
  --environment "$SCHEMA_ENV" --output-parent "$HOME"
```

`doctor` checks the interpreter, compiler/header syntax, PostgreSQL executables,
libpq paths, exact artifact-lock correspondence and protected source hashes.
It creates no output, compiler product, virtual environment, database or cache,
and makes no network request. Its `network_checked=false` result does not predict
whether acquisition will succeed. An existing compiler can be selected with
`--cc /absolute/path/to/cc`.

`prepare` downloads the 25 official wheels and psycopg2 2.9.13 source archive
through their saved official HTTPS URLs. It verifies every recorded size and
SHA-256 before accepting the file. It creates separate build and runtime virtual
environments, checks bootstrap pip 24.0, installs only the fixed setuptools
84.0.0 build backend, and builds psycopg2 with the selected `pg_config` on PATH.
Build isolation, package indexes, pip caches and automatic dependencies are
disabled. It hashes the generated wheel, writes a local wheel install lock, and
installs the 26 pins into the fresh runtime with `--require-hashes`, `--no-index`,
`--no-deps` and `--only-binary=:all:`. It then checks dependency compatibility,
the complete 27-distribution profile including pip, and compiled/runtime libpq
18.6. Failed downloads or commands are retained; no automatic retry occurs.

`run` checks the prepared profile and invokes the unchanged adapter **once** in
a new exclusive directory. It accepts no database URL. The fixed harness creates
only new loopback synthetic databases with bounded trust authentication and
stops its workers and cluster in `finally`. The wrapper preserves adapter stdout,
stderr and its own record and attempts cleanup only beneath its new owned
directory if a cluster remains. Keep this synthetic local demonstration separate
from a production database.

The final JSON contains the actual run directory, its single `portable-run.json`,
and the generated `report/report.html` and `report/summary.txt` paths. Open the HTML report to inspect all
11 scenarios, 17 worker exits and cleanup evidence. A failed check is reported as
a failure; existing historical receipts cannot satisfy a new run. If the report
module is absent, `report_status=pending` explicitly records that limitation.

## Retained outputs and boundaries

Preparation retains `environment.json`, command logs, acquired artifacts, both
virtual environments, the local wheelhouse, `install-report.json`, and
`requirements.runtime-wheels.hashed.lock` inside the new environment directory.
These are local records; the generated driver wheel and its hash depend on the
selected native build environment and are not claimed to be byte-reproducible.
The official source lock is not itself a wheel-only runtime install lock.

Each run retains `run-wrapper.json`, adapter logs, and the adapter's materialized
source copies, receipts and cluster logs. No global Python packages are changed.
Do not copy local environments or raw runtime records into a public repository:
they may contain absolute local paths. The generated portable HTML report omits
those raw paths.

Exit codes are `0` for a ready/prepared/passed result, `1` for a recorded setup or
runtime failure, and `2` for invalid/unavailable prerequisites. Review preserved
logs after a failure. Correct the cause and select a new absent environment
directory for another preparation attempt. No remote CI, different-machine run,
arbitrary migration input or production readiness is established by the local
validation.

`tools/report.py --run /exact/run/path` reinspects the saved records directly in
the terminal without creating files or connecting to PostgreSQL. Add `--json`
for review JSON, or `--output /new/report/directory` to write HTML, JSON and a
plain-text summary. `tools/sandbox.py cleanup --run-parent /exact/schema-run-xxxxxxxx`
only checks an owned stopped run; adding `--remove` explicitly deletes that run.
It does not remove the prepared environment. See the walkthrough for retained
evidence, refusal conditions and troubleshooting.

## Optional fresh PostgreSQL source build

Use the official PostgreSQL installation requirements for the build toolchain,
including GNU Make, a C compiler, Bison, Flex, Perl, tar/bzip2 and zlib development
files. The verified local build reused existing task-local Bison/Flex/m4 tools
through an explicit PATH; it installed no system package. Bison's data directory
and m4 executable must match that tool installation when using unpacked tools.
The CI workflow installs these build prerequisites only on its disposable runner.

This shell recipe follows PostgreSQL's
[VPATH build and installation procedure](https://www.postgresql.org/docs/18/install-make.html).
It acquires the fixed official archive, checks its SHA-256 before extraction,
builds outside the source tree and installs inside a new task directory. It
creates no cluster or service. It disables ICU collations and interactive
Readline; TLS support is not enabled for this local loopback example.

```sh
SCHEMA_NATIVE="$(mktemp -d "$HOME/schema-native.XXXXXXXX")"
curl --fail --location --proto '=https' --tlsv1.2 \
  https://ftp.postgresql.org/pub/source/v18.6/postgresql-18.6.tar.bz2 \
  --output "$SCHEMA_NATIVE/postgresql-18.6.tar.bz2"
printf '%s  %s\n' 555610c24d53e4316da5b7d3fc25c279d96856d5e0e23ee308c328c5fa881d9f \
  "$SCHEMA_NATIVE/postgresql-18.6.tar.bz2" | sha256sum --check -
mkdir "$SCHEMA_NATIVE/source" "$SCHEMA_NATIVE/build"
tar -xjf "$SCHEMA_NATIVE/postgresql-18.6.tar.bz2" -C "$SCHEMA_NATIVE/source"
(
  cd "$SCHEMA_NATIVE/build"
  "$SCHEMA_NATIVE/source/postgresql-18.6/configure" \
    --prefix="$SCHEMA_NATIVE/postgres" --without-icu --without-readline
  make -j2 all
  make install
)
SCHEMA_PG_BIN="$SCHEMA_NATIVE/postgres/bin"
SCHEMA_ENV="$SCHEMA_NATIVE/environment"
python3.12 -B tools/sandbox.py doctor --python /usr/bin/python3.12 \
  --pg-bin "$SCHEMA_PG_BIN" --output-parent "$SCHEMA_NATIVE"
python3.12 -B tools/sandbox.py prepare --python /usr/bin/python3.12 \
  --pg-bin "$SCHEMA_PG_BIN" --work-dir "$SCHEMA_ENV"
python3.12 -B tools/sandbox.py run \
  --environment "$SCHEMA_ENV" --output-parent "$SCHEMA_NATIVE"
```

Run the recipe in a shell that stops on errors, for example `bash -e`. Replace
the Python executable if necessary while retaining the exact 3.12.3 requirement.
The actual local acceptance used this source checksum and configure/build
commands, then a new hash-checked runtime preparation and one rehearsal against
the newly installed PostgreSQL. The 11 scenarios, 17 worker exits and cleanup
passed, and the generated report found the records consistent. It did not run a
new upstream PostgreSQL regression suite or establish reproducible binary bytes.

[`linux.yml`](../.github/workflows/linux.yml) repeats that route on Ubuntu 24.04
with Python 3.12.3, the fixed PostgreSQL source checksum, a native `RUNNER_TEMP`
prefix and the exact 26 dependency pins. Actions are pinned to commit IDs. It
prepares a fresh environment, runs the unchanged adapter once, and runs the
standard-library boundary/report tests against that run. It preserves reports
and diagnostic logs as CI artifacts. The workflow has been syntax-checked;
remote GitHub Actions execution remains unperformed.

The standard-library boundary tests need no network or database:

```sh
python3 -B -m unittest discover -s tests -p test_linux_setup.py -v
```
