"""Prepare external task-local metadata and run the unchanged accepted harness."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--pg-bin", required=True, type=Path)
    parser.add_argument("--output-parent", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "linux" or os.geteuid() == 0:
        parser.error("Use Linux as a non-root user.")
    python = args.python.absolute()  # Preserve a virtual environment's interpreter symlink.
    pg = args.pg_bin.resolve()
    parent = args.output_parent.resolve()
    if not parent.is_dir() or parent == ROOT or ROOT in parent.parents:
        parser.error("Output parent must be an existing native Linux directory outside this repository.")
    if str(parent).startswith("/mnt/"):
        parser.error("Use a native Linux output filesystem for PostgreSQL permissions.")
    if not python.is_file() or not os.access(python, os.X_OK):
        parser.error("The task-local Python executable is unavailable.")
    for name in ["postgres", "pg_ctl", "initdb", "createdb", "psql", "pg_config"]:
        if not (pg / name).is_file() or not os.access(pg / name, os.X_OK):
            parser.error(f"Missing executable: {pg / name}")
        version = subprocess.check_output([str(pg / name), "--version"], text=True).strip()
        if not version.endswith(" 18.6"):
            parser.error(f"PostgreSQL 18.6 is required: {version}")
    installed = json.loads(subprocess.check_output([str(python), "-c",
        "import importlib.metadata as m,json,platform; print(json.dumps({'python':platform.python_version(),"
        "'packages':{d.metadata['Name'].lower().replace('_','-'):d.version for d in m.distributions()}}))"], text=True))
    if installed["python"] != "3.12.3":
        parser.error("Python 3.12.3 is the recorded interpreter version.")
    for line in (ROOT / "requirements.lock").read_text().splitlines():
        name, version = line.split("==")
        if installed["packages"].get(name.lower().replace("_", "-")) != version:
            parser.error(f"Install the exact task-local dependency pin: {line}")
    sharedir = subprocess.check_output([str(pg / "pg_config"), "--sharedir"], text=True).strip()
    libdir = subprocess.check_output([str(pg / "pg_config"), "--libdir"], text=True).strip()
    if any(ch.isspace() or ch in "'\"\\," for ch in sharedir):
        parser.error("The fixed harness requires a sharedir path without whitespace, quotes, backslashes or commas.")
    subprocess.run([sys.executable, "-B", str(ROOT / "tools/verify_source.py")], check=True)
    work = parent / ("schema-migration-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    work.mkdir()
    project, native = work / "project", work / "native"
    native.mkdir()
    # The accepted harness compares two full trees; distribute one and materialize both externally.
    for relative in ["original/alembic", "components/alembic"]:
        shutil.copytree(ROOT / "components/alembic", project / relative)
    shutil.copytree(ROOT / "rehearsal", project / "rehearsal")
    evidence = project / "evidence"
    evidence.mkdir()
    shutil.copyfile(ROOT / "source-copy-manifest.json", evidence / "source-manifest.json")
    (evidence / "environment.json").write_text(json.dumps({"python": str(python), "postgres_bin": str(pg),
                                                        "native_root": str(native)}, indent=2) + "\n")
    # The improvement harness creates no extensions; upstream pytest needed separate citext/hstore setup.
    (evidence / "test-extension-inventory.json").write_text(json.dumps({"extension_search_path": sharedir}) + "\n")
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", LD_LIBRARY_PATH=libdir)
    result = {"output": str(work), "python": str(python), "postgres_bin": str(pg),
              "versions": installed, "sharedir": sharedir, "libdir": libdir}
    try:
        run = subprocess.run([str(python), "-B", str(project / "rehearsal/check_contract.py")], env=env,
                             capture_output=True, text=True)
        (work / "harness.stdout.log").write_text(run.stdout)
        (work / "harness.stderr.log").write_text(run.stderr)
        result["exit_code"] = run.returncode
        receipts = sorted(evidence.glob("rollout-*/contract-result.json"))
        result["receipts"] = [str(p) for p in receipts]
        if len(receipts) != 1:
            raise RuntimeError("Expected one preserved functional receipt.")
        receipt = json.loads(receipts[0].read_text())
        if run.returncode or receipt["status"] != "passed" or not receipt["final"]["all_stopped"]:
            raise RuntimeError("Functional check or its cleanup failed; inspect preserved output.")
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        # Fallback cleanup is confined to the unique directory just created by this invocation.
        cleanup = []
        for cluster in native.glob("rollout-*/pgdata"):
            if (cluster / "postmaster.pid").exists():
                stopped = subprocess.run([str(pg / "pg_ctl"), "-D", str(cluster), "-m", "fast", "-w", "stop"],
                                         env=env, capture_output=True, text=True)
                cleanup.append({"cluster": str(cluster), "exit_code": stopped.returncode,
                                "stdout": stopped.stdout, "stderr": stopped.stderr})
        result["fallback_cleanup"] = cleanup
        if any(item["exit_code"] for item in cleanup):
            result["status"] = "failed"
        subprocess.run([sys.executable, "-B", str(ROOT / "tools/verify_source.py")], check=True)
        (work / "portable-run.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
