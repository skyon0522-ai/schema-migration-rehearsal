"""One functional pass over the fixed recovery/compatibility contract."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import select
import socket
import subprocess
import sys
import traceback

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from worker import EXPANDED, OLD, ORIGINAL_ROWS, ROOT, SQL, snapshot

EVIDENCE = ROOT / "evidence"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def main():
    environment = json.loads((EVIDENCE / "environment.json").read_text())
    assert sys.executable == environment["python"]
    pg = Path(environment["postgres_bin"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    native = Path(environment["native_root"]) / f"rollout-{stamp}"
    native.mkdir()
    evidence = EVIDENCE / f"rollout-{stamp}"
    evidence.mkdir()
    cluster, pg_log = native / "pgdata", native / "postgres.log"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    result = {"at_utc": datetime.now(timezone.utc).isoformat(), "native": str(native), "evidence": str(evidence),
              "cluster": str(cluster), "port": port, "python": sys.executable, "cases": {}, "commands": [], "workers": []}
    processes = []
    expected_file = evidence / "expected-shape.json"
    expected = None

    def command(args, name):
        completed = subprocess.run(args, capture_output=True, text=True)
        (evidence / f"{name}.log").write_text(completed.stdout + completed.stderr)
        result["commands"].append({"command": args, "exit_code": completed.returncode})
        completed.check_returncode()
        return completed.stdout

    def fresh(uri):
        engine = create_engine(uri)
        try:
            with engine.connect() as conn:
                return snapshot(conn)
        finally:
            engine.dispose()

    def execute(uri, statement, parameters=None):
        engine = create_engine(uri)
        try:
            with engine.begin() as conn:
                if parameters is None:
                    conn.exec_driver_sql(statement)
                else:
                    conn.execute(text(statement), parameters)
        finally:
            engine.dispose()

    def database(name, fixture=None):
        command([str(pg / "createdb"), "-h", "127.0.0.1", "-p", str(port), "-U", "sql_rehearsal",
                 "-T", "template0", name], f"createdb-{name}")
        uri = f"postgresql+psycopg2://sql_rehearsal@127.0.0.1:{port}/{name}"
        execute(uri, fixture or (SQL / "fixture.sql").read_text())
        return uri

    def worker(uri, name, pause=None, expect_error=False):
        out, err = evidence / f"{name}.json", evidence / f"{name}.stderr.log"
        args = [sys.executable, str(SQL / "worker.py"), "--uri", uri, "--expected", str(expected_file), "--out", str(out)]
        if pause:
            args += ["--pause", pause]
        with err.open("w") as errors:
            process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True)
        processes.append(process)
        result["workers"].append({"name": name, "pid": process.pid, "command": args, "out": str(out), "stderr": str(err)})
        if pause:
            ready, _, _ = select.select([process.stdout], [], [], 30)
            assert ready, f"Worker did not reach {pause}"
            assert json.loads(process.stdout.readline())["barrier"] == pause
            return process, out
        process.communicate(timeout=30)
        record = json.loads(out.read_text())
        assert process.returncode == (1 if expect_error else 0), (name, process.returncode, err.read_text())
        if expect_error:
            assert record["status"] == "state_drift" and record["events"] == []
        else:
            assert record["status"] in ["completed", "already_complete"]
        result["workers"][-1]["exit_code"] = process.returncode
        return record

    def old_reader(uri):
        engine = create_engine(uri)
        try:
            with engine.connect() as conn:
                rows = [list(row) for row in conn.exec_driver_sql("SELECT id, mood::text, payload FROM rehearsal.items ORDER BY id")]
            for row in rows:
                if row[1] not in OLD:
                    raise ValueError(f"Old reader rejects stored label {row[1]!r} at row {row[0]}")
            return rows
        finally:
            engine.dispose()

    def old_client(uri, row_id, reject_new=False):
        before = old_reader(uri)
        execute(uri, "INSERT INTO rehearsal.items VALUES (:id, 'sad', 'old-client')", {"id": row_id})
        execute(uri, "UPDATE rehearsal.items SET mood='ok' WHERE id=:id", {"id": row_id})
        after = old_reader(uri)
        assert [row for row in after if row[0] == row_id] == [[row_id, "ok", "old-client"]]
        record = {"read_before": before, "read_after_insert_update": after}
        if reject_new:
            try:
                execute(uri, "INSERT INTO rehearsal.items VALUES (999, 'soso', 'premature')")
            except DBAPIError as error:
                record["rejected_new_label"] = {"sqlstate": error.orig.pgcode, "constraint": error.orig.diag.constraint_name}
                assert record["rejected_new_label"] == {"sqlstate": "23514", "constraint": "legacy_labels"}
            else:
                raise AssertionError("Compatibility gate accepted soso")
        state = fresh(uri)
        assert [row for row in state["rows"] if row["id"] in [1, 2, 3]] == ORIGINAL_ROWS
        assert all(row["id"] != 999 for row in state["rows"])
        record["readback"] = state
        return record

    def resume_twice(uri, name):
        resumed = worker(uri, f"{name}-resume")
        before = fresh(uri)
        again = worker(uri, f"{name}-resume-again")
        after = fresh(uri)
        assert before == after and again["status"] == "already_complete"
        assert after["labels"] == EXPANDED and after["marker"] == [{"id": 1, "completed": True}]
        assert [row for row in after["rows"] if row["id"] in [1, 2, 3]] == ORIGINAL_ROWS
        return {"resume": resumed, "resume_again": again, "before_second": before, "after_second": after,
                "unchanged_sha256": digest(after)}

    try:
        command([str(pg / "initdb"), "-D", str(cluster), "-U", "sql_rehearsal", "--auth=trust", "--no-locale", "--encoding=UTF8"], "initdb")
        extension_path = json.loads((EVIDENCE / "test-extension-inventory.json").read_text())["extension_search_path"]
        command([str(pg / "pg_ctl"), "-D", str(cluster), "-l", str(pg_log), "-o",
                 f"-h 127.0.0.1 -p {port} -c unix_socket_directories= -c log_statement=all -c extension_control_path={extension_path}", "-w", "start"], "start")
        result["postgres_pid"] = int((cluster / "postmaster.pid").read_text().splitlines()[0])
        uri = database("normal")
        state = fresh(uri)
        assert state["labels"] == OLD and state["rows"] == ORIGINAL_ROWS and state["marker"] == []
        expected = state["shape"]
        expected_file.write_text(json.dumps(expected, indent=2) + "\n")
        normal = {"fixture": state, "old_before": old_client(uri, 100)}
        normal["expansion"] = worker(uri, "normal-expansion")
        normal["old_after"] = old_client(uri, 101, reject_new=True)
        normal["repeat"] = resume_twice(uri, "normal")
        result["cases"]["normal_and_old_clients"] = normal
        for name, pause in [("stop_before_expansion", "before-expansion"), ("stop_after_durable_expansion", "after-marker-insert")]:
            uri = database(name)
            process, out = worker(uri, name, pause=pause)
            record = {"fresh_at_barrier": fresh(uri), "worker_at_barrier": json.loads(out.read_text())}
            assert record["fresh_at_barrier"]["marker"] == []
            assert record["fresh_at_barrier"]["labels"] == (OLD if pause == "before-expansion" else EXPANDED)
            if pause == "after-marker-insert":
                assert record["worker_at_barrier"]["marker_visible_inside_worker_transaction"] == [{"id": 1, "completed": True}]
            record["old_during_barrier"] = old_client(uri, 100, reject_new=pause == "after-marker-insert")
            process.kill()
            process.wait(timeout=10)
            assert process.returncode == -9
            result["workers"][-1]["exit_code"] = process.returncode
            record["termination"] = {"pid": process.pid, "signal": "SIGKILL", "exit_code": process.returncode}
            record["fresh_after_kill"] = fresh(uri)
            assert record["fresh_after_kill"] == record["old_during_barrier"]["readback"]
            record["resumption"] = resume_twice(uri, name)
            result["cases"][name] = record
        drift = {
            "wrong_schema": "ALTER SCHEMA rehearsal RENAME TO alien",
            "wrong_type": "ALTER TYPE rehearsal.mood RENAME TO mood_unused; CREATE DOMAIN rehearsal.mood AS text; ALTER TABLE rehearsal.items ALTER COLUMN mood TYPE rehearsal.mood USING mood::text",
            "wrong_table": "ALTER TABLE rehearsal.items ADD COLUMN unexpected integer DEFAULT 0",
            "wrong_gate": "ALTER TABLE rehearsal.items DROP CONSTRAINT legacy_labels",
            "contradictory_marker": "INSERT INTO rehearsal.rollout_marker VALUES (1, true)",
            "changed_original_row": "UPDATE rehearsal.items SET payload='changed' WHERE id=2",
            "wrong_label_order": None,
        }
        for name, change in drift.items():
            fixture = (SQL / "fixture.sql").read_text()
            if name == "wrong_label_order":
                fixture = fixture.replace("ENUM ('sad', 'ok', 'happy')", "ENUM ('ok', 'sad', 'happy')")
            uri = database(name, fixture)
            if change:
                execute(uri, change)
            before = fresh(uri)
            # Wrong-schema data is also read back from its renamed, fixed schema.
            alien_before = None
            if name == "wrong_schema":
                engine = create_engine(uri)
                with engine.connect() as conn:
                    alien_before = [row[0] for row in conn.exec_driver_sql("SELECT to_jsonb(item) FROM alien.items item ORDER BY id")]
                engine.dispose()
            rejected = worker(uri, name, expect_error=True)
            after = fresh(uri)
            assert before == after
            if alien_before is not None:
                engine = create_engine(uri)
                with engine.connect() as conn:
                    alien_after = [row[0] for row in conn.exec_driver_sql("SELECT to_jsonb(item) FROM alien.items item ORDER BY id")]
                engine.dispose()
                assert alien_before == alien_after
            result["cases"][name] = {"before": before, "after": after, "state_sha256": digest(after),
                                      "rejected": rejected, "renamed_schema_rows": alien_before}
        uri = database("activation_negative_control")
        expanded = worker(uri, "activation-expansion")
        read_before = old_reader(uri)
        execute(uri, (SQL / "activation.sql").read_text())
        activated = fresh(uri)
        try:
            old_reader(uri)
        except ValueError as error:
            failure = str(error)
        else:
            raise AssertionError("Old closed-set reader missed activation incompatibility")
        assert {"id": 200, "mood": "soso", "payload": "explicit-activation"} in activated["rows"]
        result["cases"]["activation_negative_control"] = {"expanded": expanded, "old_read_before": read_before,
                                                          "activated_readback": activated, "old_reader_failure": failure}
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        if (cluster / "postmaster.pid").exists():
            command([str(pg / "pg_ctl"), "-D", str(cluster), "-m", "fast", "-w", "stop"], "stop")
        status = subprocess.run([str(pg / "pg_ctl"), "-D", str(cluster), "status"], capture_output=True, text=True)
        with socket.socket() as probe:
            port_open = probe.connect_ex(("127.0.0.1", port)) == 0
        result["final"] = {"pg_ctl_status": status.returncode, "postmaster_pid_exists": (cluster / "postmaster.pid").exists(),
                           "port_open": port_open, "workers_stopped": all(p.poll() is not None for p in processes)}
        result["final"]["all_stopped"] = status.returncode == 3 and not port_open and not result["final"]["postmaster_pid_exists"] and result["final"]["workers_stopped"]
        manifest = json.loads((EVIDENCE / "source-manifest.json").read_text())["source_files"]
        result["source_unchanged"] = {}
        for label in ["original", "components"]:
            directory = ROOT / label / "alembic"
            live = {str(p.relative_to(directory)): {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                    for p in directory.rglob("*") if p.is_file()}
            result["source_unchanged"][label] = live == manifest
        result["extension_body_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in SQL.iterdir() if p.is_file()}
        if pg_log.exists():
            (evidence / "postgres.log").write_bytes(pg_log.read_bytes())
        receipt = evidence / "contract-result.json"
        receipt.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"receipt": str(receipt), "status": result["status"], "cases": list(result["cases"]),
                          "error": result.get("error"), "final": result["final"], "source_unchanged": result["source_unchanged"]}, indent=2))
    return 0 if result["status"] == "passed" and result["final"]["all_stopped"] and all(result["source_unchanged"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
