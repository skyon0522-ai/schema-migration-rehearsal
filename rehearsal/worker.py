"""One fixed enum rehearsal, using the preserved copied Alembic runner."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SQL = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "components/alembic"))
import alembic
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, event, text

OLD = ["sad", "ok", "happy"]
EXPANDED = OLD + ["soso"]
ORIGINAL_ROWS = [{"id": 1, "mood": "sad", "payload": "alpha"},
                 {"id": 2, "mood": "ok", "payload": "beta"},
                 {"id": 3, "mood": "happy", "payload": "gamma"}]
parts = re.split(r"-- query: (\w+)\n", (SQL / "verification.sql").read_text())
QUERIES = dict(zip(parts[1::2], parts[2::2]))


class StateDrift(ValueError):
    pass


def snapshot(conn):
    query = lambda name: conn.execute(text(QUERIES[name]), {"schema": "rehearsal"}).all()
    state = {"schema_exists": query("schema")[0][0],
             "shape": {name: [list(row) for row in query(name)] for name in ["type", "relations", "columns", "constraints"]},
             "labels": [row[0] for row in query("labels")], "rows": [], "marker": []}
    relations = {row[0] for row in state["shape"]["relations"]}
    if "items" in relations:
        state["rows"] = [row[0] for row in query("rows")]
    if "rollout_marker" in relations:
        state["marker"] = [row[0] for row in query("marker")]
    return state


def validate(state, expected):
    if not state["schema_exists"] or state["shape"] != expected:
        raise StateDrift("Schema/type/table/constraint shape differs from the fixed fixture")
    if state["labels"] not in [OLD, EXPANDED]:
        raise StateDrift("Unexpected enum labels or order")
    if [row for row in state["rows"] if row["id"] in [1, 2, 3]] != ORIGINAL_ROWS:
        raise StateDrift("Original fixture rows differ")
    if any(row["mood"] not in OLD for row in state["rows"]):
        raise StateDrift("Stored rows violate the compatibility window")
    if state["marker"] not in [[], [{"id": 1, "completed": True}]]:
        raise StateDrift("Unexpected completion marker")
    if state["marker"] and state["labels"] != EXPANDED:
        raise StateDrift("Completion marker contradicts the enum state")


def rehearse(uri, expected, out, pause=None):
    source = Path(inspect.getsourcefile(MigrationContext)).resolve()
    assert source == (ROOT / "components/alembic/alembic/runtime/migration.py").resolve()
    record = {"status": "running", "events": [], "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "alembic_file": alembic.__file__, "unwrapped_code_source": MigrationContext.autocommit_block.__wrapped__.__code__.co_filename}
    save = lambda: out.write_text(json.dumps(record, indent=2) + "\n")

    def barrier(name):
        record["events"].append({"barrier": name})
        save()
        if pause == name:
            print(json.dumps({"barrier": name}), flush=True)
            sys.stdin.readline()

    def profile(frame, action, arg):
        if frame.f_code.co_name == "autocommit_block" and frame.f_code.co_filename == str(source):
            record["events"].append({"autocommit_frame": action, "line": frame.f_lineno, "source": frame.f_code.co_filename})

    engine = create_engine(uri)
    previous_profile = sys.getprofile()
    try:
        with engine.connect() as conn:
            record["before"] = state = snapshot(conn)
            validate(state, expected)
            conn.rollback()  # Finish inspection reads before the copied context manages transactions.
            if state["marker"]:
                record.update(status="already_complete", after=state)
                return record
            barrier("before-expansion")
            context = MigrationContext.configure(conn, opts={"transaction_per_migration": True})

            def observed_sql(connection, cursor, statement, parameters, execution_context, executemany):
                record["events"].append({"sql": statement, "dbapi_autocommit": connection.connection.driver_connection.autocommit})

            event.listen(conn, "before_cursor_execute", observed_sql)
            sys.setprofile(profile)
            with context.begin_transaction(_per_migration=True):
                with context.autocommit_block():
                    context.execute(text((SQL / "expand.sql").read_text()))
            sys.setprofile(previous_profile)
            event.remove(conn, "before_cursor_execute", observed_sql)
            record["expanded"] = expanded = snapshot(conn)
            validate(expanded, expected)
            if expanded["labels"] != EXPANDED or expanded["marker"]:
                raise StateDrift("Expansion did not reach the expected unmarked state")
            conn.rollback()
            with conn.begin():
                conn.execute(text("INSERT INTO rehearsal.rollout_marker VALUES (1, true)"))
                record["marker_visible_inside_worker_transaction"] = snapshot(conn)["marker"]
                barrier("after-marker-insert")
            record["after"] = snapshot(conn)
            validate(record["after"], expected)
            record["status"] = "completed"
            return record
    except StateDrift as exc:
        record.update(status="state_drift", error=str(exc))
        raise
    finally:
        sys.setprofile(previous_profile)
        engine.dispose()
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pause", choices=["before-expansion", "after-marker-insert"])
    args = parser.parse_args()
    rehearse(args.uri, json.loads(args.expected.read_text()), args.out, args.pause)
