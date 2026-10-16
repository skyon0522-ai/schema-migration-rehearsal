"""Prepare the recorded Linux profile or run its unchanged contract once."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "verification/fresh/artifact-metadata.json"
OFFICIAL_LOCK = ROOT / "requirements.official-artifacts.hashed.lock"
PACKAGE_QUERY = ("import importlib.metadata as m,json,platform;print(json.dumps("
                 "{'python':platform.python_version(),'packages':{d.metadata['Name'].lower().replace('_','-'):"
                 "d.version for d in m.distributions()}}))")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def native_directory(path):
    """Do not let aliases or mounted Windows output escape the selected directory."""
    path = Path(os.path.abspath(path.expanduser()))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Output paths must not contain symlinks")
    if path == ROOT or ROOT in path.parents:
        raise ValueError("Output must be outside this checkout")
    if not path.is_dir() or path == Path("/mnt") or Path("/mnt") in path.parents:
        raise ValueError("Choose an existing native Linux directory outside /mnt")
    if not os.access(path, os.W_OK | os.X_OK):
        raise ValueError("Output parent must be writable and searchable")
    return path


def executable(path):
    path = Path(os.path.abspath(Path(path).expanduser()))
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("Selected executable is unavailable: " + str(path))
    return path


def clean_env(pg=None, compiler=None, libdir=None):
    env = os.environ.copy()
    for name in list(env):
        if name.startswith("PIP_"):
            env.pop(name)
    for name in ("PYTHONHOME", "PYTHONPATH", "PIP_TARGET", "PIP_PREFIX", "PIP_USER",
                 "CFLAGS", "CPPFLAGS", "LDFLAGS", "LDSHARED"):
        env.pop(name, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PIP_CONFIG_FILE=os.devnull,
               PIP_NO_INPUT="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_CACHE_DIR="1")
    if pg:
        env["PATH"] = str(pg) + os.pathsep + os.defpath
    if compiler:
        env["CC"] = str(compiler)
    if libdir:
        env["LD_LIBRARY_PATH"] = str(libdir)
    return env


def inspect(command, env, input_text=None):
    return subprocess.run([str(item) for item in command], input=input_text, env=env,
                          capture_output=True, text=True, timeout=30, check=True).stdout.strip()


def pinned_artifacts():
    pins = {}
    for line in OFFICIAL_LOCK.read_text().splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^ ]+) --hash=sha256:([0-9a-f]{64})", line)
        if not match:
            raise ValueError("Official artifact lock has an invalid entry")
        name, version, sha = match.groups()
        key = name.lower().replace("_", "-")
        if key in pins:
            raise ValueError("Official artifact lock repeats a package")
        pins[key] = (version, sha)
    artifacts = json.loads(METADATA.read_text())["official_artifacts"]
    seen = set()
    for item in artifacts:
        key = item["name"].lower().replace("_", "-")
        url = urlsplit(item["url"])
        filename = item["filename"]
        if (key in seen or pins.get(key) != (item["version"], item["sha256"])
                or url.scheme != "https" or url.netloc != "files.pythonhosted.org"
                or url.query or url.fragment or Path(filename).name != filename
                or not url.path.endswith("/" + filename) or not item["official_digest_equal"]):
            raise ValueError("Saved official metadata and artifact lock disagree")
        seen.add(key)
    version_pins = {line.split("==")[0].lower().replace("_", "-"): line.split("==")[1]
                    for line in (ROOT / "requirements.lock").read_text().splitlines()}
    if (len(pins) != 26 or seen != set(pins) or version_pins != {key: value[0] for key, value in pins.items()}
            or sum(item["artifact_type"] == "bdist_wheel" for item in artifacts) != 25
            or [item["name"] for item in artifacts if item["artifact_type"] != "bdist_wheel"] != ["psycopg2"]):
        raise ValueError("Expected exactly 25 official wheels and the pinned psycopg2 source")
    return artifacts


def doctor(output_parent, python, pg_bin, compiler=None):
    """Read-only preflight: no directories, downloads, compiler output or services."""
    if sys.platform != "linux" or os.geteuid() == 0:
        raise ValueError("Use Linux as a non-root user")
    parent = native_directory(output_parent)
    python = executable(python)
    pg = Path(pg_bin).expanduser()
    if not pg.is_dir():
        raise ValueError("PostgreSQL bin directory is unavailable; supply --pg-bin for a complete existing PostgreSQL 18.6 installation: " + str(pg))
    pg = pg.resolve(strict=True)
    env = clean_env()
    profile = json.loads(inspect([python, "-B", "-c", "import ensurepip,json,platform,sysconfig;"
        "print(json.dumps({'python':platform.python_version(),'implementation':platform.python_implementation(),"
        "'machine':platform.machine(),'system':platform.system(),'libc':platform.libc_ver(),"
        "'include':sysconfig.get_path('include'),'bootstrap_pip':ensurepip.version()}))"], env))
    if (profile["python"] != "3.12.3" or profile["implementation"] != "CPython"
            or profile["machine"] != "x86_64" or profile["system"] != "Linux"
            or profile["libc"][0] != "glibc" or tuple(map(int, profile["libc"][1].split("."))) < (2, 17)
            or profile["bootstrap_pip"] != "24.0"):
        raise ValueError("The recorded profile requires Linux x86_64, glibc >=2.17, CPython 3.12.3 and bundled pip 24.0")
    include = Path(profile["include"])
    if not all((include / name).is_file() for name in ("Python.h", "pyconfig.h")):
        raise ValueError("Install development headers matching the selected Python 3.12.3")
    versions = {}
    for name in ("postgres", "pg_ctl", "initdb", "createdb", "psql", "pg_config"):
        versions[name] = inspect([executable(pg / name), "--version"], env)
        if not versions[name].endswith(" 18.6"):
            raise ValueError("Every selected PostgreSQL executable must be version 18.6")
    pg_paths = {name: inspect([pg / "pg_config", "--" + name], env)
                for name in ("bindir", "includedir", "libdir", "sharedir")}
    if Path(pg_paths["bindir"]).resolve() != pg:
        raise ValueError("pg_config must describe the selected PostgreSQL installation")
    if any(ch.isspace() or ch in "'\"\\," for ch in pg_paths["sharedir"]):
        raise ValueError("The fixed harness requires sharedir without whitespace, quotes, backslashes or commas")
    pg_include, libdir = Path(pg_paths["includedir"]), Path(pg_paths["libdir"])
    if not (pg_include / "libpq-fe.h").is_file() or not (libdir / "libpq.so").is_file():
        raise ValueError("The selected PostgreSQL installation needs its libpq headers and shared library")
    if not (Path(pg_paths["sharedir"]) / "postgres.bki").is_file():
        raise ValueError("The selected PostgreSQL installation needs its initdb shared data")
    compiler = executable(compiler or shutil.which("cc") or "/missing-c-compiler")
    compiler_version = inspect([compiler, "--version"], env).splitlines()[0]
    inspect([compiler, "-x", "c", "-fsyntax-only", "-I" + str(include), "-I" + str(pg_include), "-"], env,
            "#include <Python.h>\n#include <libpq-fe.h>\nint main(void) { return 0; }\n")
    source = json.loads(inspect([sys.executable, "-B", ROOT / "tools/verify_source.py"], env))
    pinned_artifacts()
    return {"status": "ready", "python": str(python), "python_profile": profile,
            "postgres_bin": str(pg), "postgres_versions": versions, "postgres_paths": pg_paths,
            "compiler": str(compiler), "compiler_version": compiler_version, "source": source,
            "official_artifacts": 26, "state_created": False, "network_checked": False}, parent


def logged(command, work, label, commands, env):
    command = [str(item) for item in command]
    with (work / "logs" / (label + ".stdout.log")).open("xb") as out, (work / "logs" / (label + ".stderr.log")).open("xb") as err:
        result = subprocess.run(command, cwd=work, stdout=out, stderr=err, env=env)
    commands.append({"label": label, "command": command, "exit_code": result.returncode})
    if result.returncode:
        raise ValueError("Command failed; inspect preserved logs: " + label)
    return (work / "logs" / (label + ".stdout.log")).read_text().strip()


def prepare(work_dir, preflight):
    work = Path(os.path.abspath(work_dir.expanduser()))
    native_directory(work.parent)
    if work.exists() or work.is_symlink():
        raise ValueError("Preparation directory must not already exist")
    # mkdir without exist_ok is the final race check; every later write is under this new directory.
    work.mkdir(mode=0o700)
    record = {"schema_version": 1, "status": "failed", "preflight": preflight,
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "commands": [], "artifacts": []}
    pg = Path(preflight["postgres_bin"])
    env = clean_env(pg, preflight["compiler"], preflight["postgres_paths"]["libdir"])
    try:
        for name in ("logs", "artifacts", "wheelhouse", "tmp"):
            (work / name).mkdir(mode=0o700)
        env["TMPDIR"] = str(work / "tmp")
        artifacts = pinned_artifacts()
        for item in artifacts:
            destination = work / "artifacts" / item["filename"]
            partial = destination.with_name(destination.name + ".partial")
            with urlopen(item["url"], timeout=60) as response, partial.open("xb") as stream:
                if urlsplit(response.url).scheme != "https" or urlsplit(response.url).netloc != "files.pythonhosted.org":
                    raise ValueError("Official download redirected outside the selected HTTPS host")
                shutil.copyfileobj(response, stream)
            if partial.stat().st_size != item["bytes"] or digest(partial) != item["sha256"]:
                raise ValueError("Downloaded artifact failed its recorded size or SHA-256 check")
            partial.rename(destination)
            record["artifacts"].append({"name": item["name"], "filename": item["filename"],
                "url": item["url"], "sha256": digest(destination), "bytes": destination.stat().st_size})
            if item["artifact_type"] == "bdist_wheel":
                shutil.copyfile(destination, work / "wheelhouse" / destination.name)
        commands = record["commands"]
        for name in ("build-venv", "venv"):
            logged([preflight["python"], "-B", "-m", "venv", work / name], work, "create-" + name, commands, env)
            bootstrap = json.loads(logged([work / name / "bin/python", "-B", "-c", PACKAGE_QUERY], work,
                                         name + "-bootstrap", commands, env))
            if bootstrap != {"python": "3.12.3", "packages": {"pip": "24.0"}}:
                raise ValueError("Fresh virtual environments must contain only bootstrap pip 24.0")
        build_python = work / "build-venv/bin/python"
        backend = next(item for item in artifacts if item["name"] == "setuptools")
        backend_lock = work / "requirements.build.hashed.lock"
        backend_lock.write_text("setuptools==84.0.0 --hash=sha256:" + backend["sha256"] + "\n")
        install = ["-B", "-m", "pip", "install", "--no-index", "--no-deps", "--no-cache-dir", "--require-hashes",
                   "--only-binary=:all:", "--find-links", work / "wheelhouse"]
        logged([build_python, *install, "-r", backend_lock], work, "install-build-backend", commands, env)
        source = next(item for item in artifacts if item["name"] == "psycopg2")
        logged([build_python, "-B", "-m", "pip", "wheel", "--no-index", "--no-deps", "--no-build-isolation",
                "--no-cache-dir", "--wheel-dir", work / "wheelhouse", work / "artifacts" / source["filename"]],
               work, "build-psycopg2", commands, env)
        wheels = list((work / "wheelhouse").glob("psycopg2-2.9.13-*.whl"))
        if len(wheels) != 1:
            raise ValueError("Expected exactly one locally built psycopg2 wheel")
        wheel = wheels[0]
        record["local_build"] = {"filename": wheel.name, "sha256": digest(wheel), "bytes": wheel.stat().st_size,
                                 "pg_config": str(pg / "pg_config")}
        runtime_lock = work / "requirements.runtime-wheels.hashed.lock"
        runtime_lock.write_text("\n".join(item["name"] + "==" + item["version"] + " --hash=sha256:" +
            (digest(wheel) if item["name"] == "psycopg2" else item["sha256"]) for item in artifacts) + "\n")
        python = work / "venv/bin/python"
        logged([python, *install, "--report", work / "install-report.json", "-r", runtime_lock], work,
               "install-runtime", commands, env)
        logged([python, "-B", "-m", "pip", "check"], work, "pip-check", commands, env)
        installed = json.loads(logged([python, "-B", "-c", PACKAGE_QUERY], work, "installed-profile", commands, env))
        expected = {item["name"].lower().replace("_", "-"): item["version"] for item in artifacts}
        if installed != {"python": "3.12.3", "packages": {**expected, "pip": "24.0"}}:
            raise ValueError("Fresh runtime differs from the 26 pins plus bootstrap pip 24.0")
        driver = json.loads(logged([python, "-B", "-c", "import psycopg2,psycopg2.extensions,json;"
            "print(json.dumps({'compiled_libpq':psycopg2.__libpq_version__,"
            "'runtime_libpq':psycopg2.extensions.libpq_version()}))"], work, "driver-profile", commands, env))
        if driver != {"compiled_libpq": 180006, "runtime_libpq": 180006}:
            raise ValueError("psycopg2 must compile and load the selected libpq 18.6")
        record.update(status="prepared", python=str(python), postgres_bin=str(pg), installed=installed,
                      driver=driver, runtime_lock_sha256=digest(runtime_lock),
                      official_lock_sha256=digest(OFFICIAL_LOCK), metadata_sha256=digest(METADATA))
    except (OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        record["error"] = str(error) or type(error).__name__
    finally:
        record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(work / "environment.json", record)
    return record, work


def prepared_environment(path):
    path = native_directory(path)
    record = json.loads((path / "environment.json").read_text())
    if (not isinstance(record, dict) or record.get("status") != "prepared" or record.get("official_lock_sha256") != digest(OFFICIAL_LOCK)
            or record.get("metadata_sha256") != digest(METADATA)
            or record.get("runtime_lock_sha256") != digest(path / "requirements.runtime-wheels.hashed.lock")
            or record.get("python") != str(path / "venv/bin/python")):
        raise ValueError("Prepared environment receipt is invalid or differs from this checkout")
    return record


def run_once(environment, output_parent):
    record = prepared_environment(environment)
    preflight, parent = doctor(output_parent, record["python"], record["postgres_bin"], record["preflight"]["compiler"])
    env = clean_env(Path(record["postgres_bin"]), libdir=preflight["postgres_paths"]["libdir"])
    installed = json.loads(inspect([record["python"], "-B", "-c", PACKAGE_QUERY], env))
    if installed != record["installed"]:
        raise ValueError("Prepared runtime packages have changed")
    run = Path(tempfile.mkdtemp(prefix="schema-run-", dir=parent))
    os.chmod(run, 0o700)
    result = {"schema_version": 1, "status": "failed", "adapter_invocations": 1,
              "run_parent": str(run), "environment": str(environment), "fallback_cleanup": [],
              "ownership_token": uuid.uuid4().hex}
    write_json(run / "run-owner.json", {"product": "schema-migration-rehearsal", "kind": "run",
        "run_parent": str(run), "ownership_token": result["ownership_token"]})
    child = None
    def interrupt(*_):
        raise KeyboardInterrupt
    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        with (run / "adapter.stdout.log").open("xb") as out, (run / "adapter.stderr.log").open("xb") as err:
            child = subprocess.Popen([sys.executable, "-B", str(ROOT / "tools/run_contract.py"), "--python", record["python"],
                "--pg-bin", record["postgres_bin"], "--output-parent", str(run)], cwd=ROOT, env=env,
                stdout=out, stderr=err, start_new_session=True)
            result["adapter_exit"] = child.wait()
    except KeyboardInterrupt:
        result.update(status="interrupted", adapter_exit=130)
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGINT)
            try:
                child.wait(timeout=45)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result["error"] = str(error) or type(error).__name__
    finally:
        signal.signal(signal.SIGTERM, previous)
        # Only the exclusive adapter parent is searched; never address any existing cluster or service.
        for cluster in run.glob("schema-migration-*/native/rollout-*/pgdata"):
            if (cluster / "postmaster.pid").exists():
                if (not cluster.resolve().is_relative_to(run)
                        or any(path.is_symlink() for path in (cluster, *cluster.parents))):
                    result["fallback_cleanup"].append({"cluster": str(cluster), "exit_code": None,
                                                        "error": "Cluster path escapes the owned run"})
                    continue
                try:
                    stopped = subprocess.run([str(Path(record["postgres_bin"]) / "pg_ctl"), "-D", str(cluster),
                        "-m", "fast", "-w", "stop"], env=env, capture_output=True, text=True, timeout=45)
                    result["fallback_cleanup"].append({"cluster": str(cluster), "exit_code": stopped.returncode,
                                                        "stdout": stopped.stdout, "stderr": stopped.stderr})
                except (OSError, subprocess.SubprocessError) as error:
                    result["fallback_cleanup"].append({"cluster": str(cluster), "exit_code": None, "error": str(error)})
        receipts = list(run.glob("schema-migration-*/portable-run.json"))
        if len(receipts) == 1:
            portable = receipts[0]
            result.update(run=str(portable.parent), portable_run=str(portable))
            try:
                receipt = json.loads(portable.read_text())
                if not isinstance(receipt, dict):
                    raise ValueError("Portable receipt must be an object")
                if (result.get("adapter_exit") == 0 and receipt.get("status") == "passed"
                        and all(item["exit_code"] == 0 for item in result["fallback_cleanup"])):
                    result["status"] = "passed"
                if (ROOT / "tools/report.py").is_file():
                    from report import write_report
                    review = write_report(portable.parent, portable.parent / "report")
                    result.update(report=str(portable.parent / "report/report.html"), report_status=review["status"],
                                  summary=str(portable.parent / "report/summary.txt"))
                    if not review["evidence_passed"]:
                        result["status"] = "failed"
                else:
                    result["report_status"] = "pending"
            except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
                result.update(status="failed", report_status="failed", error="Receipt or report validation failed: " + str(error))
        else:
            result["error"] = "Expected exactly one portable-run.json beneath the new adapter parent"
        write_json(run / "run-wrapper.json", result)
    return result


def cleanup_run(path, remove=False):
    """Remove only an explicitly selected, recognized wrapper-owned stopped run."""
    if sys.platform != "linux" or os.geteuid() == 0:
        raise ValueError("Use Linux as a non-root user")
    run = native_directory(path)
    if run != run.resolve(strict=True) or not re.fullmatch(r"schema-run-[a-z0-9_]{8}", run.name):
        raise ValueError("Cleanup requires the exact schema-run-xxxxxxxx directory printed by run")
    if any(item.is_symlink() for item in run.iterdir()):
        raise ValueError("Run contains a symlink; no files were removed")
    owner = json.loads((run / "run-owner.json").read_text())
    receipt = json.loads((run / "run-wrapper.json").read_text())
    if (not isinstance(owner, dict) or not isinstance(receipt, dict)
            or owner.get("product") != "schema-migration-rehearsal" or owner.get("kind") != "run"
            or owner.get("run_parent") != str(run) or receipt.get("run_parent") != str(run)
            or not re.fullmatch(r"[0-9a-f]{32}", str(owner.get("ownership_token", "")))
            or owner["ownership_token"] != receipt.get("ownership_token")
            or receipt.get("adapter_invocations") != 1):
        raise ValueError("Cleanup requires matching ownership and wrapper records; preserve this directory for inspection")
    children = list(run.iterdir())
    expected = {"run-owner.json", "run-wrapper.json", "adapter.stdout.log", "adapter.stderr.log"}
    artifacts = [item for item in children if item.name.startswith("schema-migration-") and item.is_dir()]
    if len(artifacts) != 1 or {item.name for item in children} != expected | {artifacts[0].name}:
        raise ValueError("Unrecognized run contents; no files were removed")
    def incomplete(error):
        raise ValueError("Run cannot be fully inspected; no files were removed: " + str(error)) from error
    for root, directories, files in os.walk(run, followlinks=False, onerror=incomplete):
        if any((Path(root) / name).is_symlink() for name in directories + files):
            raise ValueError("Run contains a symlink; no files were removed")
        if "postmaster.pid" in files:
            raise ValueError("Run contains postmaster.pid; verify and stop only that owned cluster before cleanup")
    # These local markers prevent accidental selection; they do not authenticate editable records.
    result = {"status": "removed" if remove else "cleanup_ready", "run_parent": str(run),
              "removed": remove, "environment_removed": False}
    if remove:
        shutil.rmtree(run)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "prepare", "run", "cleanup"))
    parser.add_argument("--python", type=Path, default=Path(sys.executable), help="Existing CPython 3.12.3 executable")
    parser.add_argument("--pg-bin", type=Path, help="Existing PostgreSQL 18.6 installation's bin directory")
    parser.add_argument("--cc", type=Path, help="Existing C compiler, otherwise cc on PATH")
    parser.add_argument("--output-parent", type=Path, default=Path.home(), help="Existing native Linux directory outside the checkout")
    parser.add_argument("--work-dir", type=Path, help="New native Linux directory required by prepare")
    parser.add_argument("--environment", type=Path, help="Prepared directory required by run")
    parser.add_argument("--run-parent", type=Path, help="Exact wrapper-owned run directory required by cleanup")
    parser.add_argument("--remove", action="store_true", help="Delete the explicitly selected stopped run; cleanup otherwise only inspects")
    args = parser.parse_args(argv)
    try:
        if args.remove and args.command != "cleanup":
            raise ValueError("--remove is valid only with cleanup")
        if args.command == "cleanup":
            if not args.run_parent:
                raise ValueError("cleanup requires --run-parent naming the exact owned run")
            result = cleanup_run(args.run_parent, args.remove)
        elif args.command == "run":
            if not args.environment:
                raise ValueError("run requires --environment")
            result = run_once(args.environment, args.output_parent)
        else:
            if not args.pg_bin:
                raise ValueError("doctor and prepare require an explicit --pg-bin")
            parent = args.work_dir.parent if args.command == "prepare" and args.work_dir else args.output_parent
            preflight, _ = doctor(parent, args.python, args.pg_bin, args.cc)
            if args.command == "doctor":
                result = preflight
            else:
                if not args.work_dir:
                    raise ValueError("prepare requires --work-dir naming an absent directory")
                result, work = prepare(args.work_dir, preflight)
                result = {"status": result["status"], "environment": str(work), "receipt": str(work / "environment.json"),
                          "error": result.get("error")}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(str(error) or type(error).__name__, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in ("ready", "prepared", "passed", "cleanup_ready", "removed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
