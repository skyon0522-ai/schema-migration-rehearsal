"""Standard-library checks for preparation boundaries; no network or database."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("schema_sandbox", ROOT / "tools/sandbox.py")
sandbox = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sandbox)


@unittest.skipUnless(sys.platform == "linux", "Native Linux path protections")
class LinuxSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="schema-preflight-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_native_parent_is_read_only(self):
        before = list(self.directory.iterdir())
        self.assertEqual(sandbox.native_directory(self.directory), self.directory)
        self.assertEqual(before, list(self.directory.iterdir()))

    def test_symlink_parent_and_child_are_rejected(self):
        target = self.directory / "actual"
        target.mkdir()
        (target / "child").mkdir()
        alias = self.directory / "alias"
        alias.symlink_to(target, target_is_directory=True)
        for path in (alias, alias / "child"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "symlink"):
                sandbox.native_directory(path)

    def test_checkout_and_mounted_output_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "checkout"):
            sandbox.native_directory(ROOT)
        with self.assertRaisesRegex(ValueError, "native Linux"):
            sandbox.native_directory(Path("/mnt"))

    def test_prepare_cannot_overwrite_even_before_work_starts(self):
        sentinel = self.directory / "keep.txt"
        sentinel.write_text("preserve me")
        with self.assertRaisesRegex(ValueError, "already exist"), patch.object(sandbox, "urlopen") as network:
            sandbox.prepare(self.directory, {})
        network.assert_not_called()
        self.assertEqual(sentinel.read_text(), "preserve me")
        self.assertEqual([path.name for path in self.directory.iterdir()], ["keep.txt"])

    def test_prepare_does_not_follow_dangling_symlink(self):
        alias = self.directory / "new"
        target = self.directory / "missing"
        alias.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "already exist"):
            sandbox.prepare(alias, {})
        self.assertFalse(target.exists())

    def test_saved_artifacts_have_exact_lock_and_one_source(self):
        artifacts = sandbox.pinned_artifacts()
        self.assertEqual(len(artifacts), 26)
        self.assertEqual(sum(item["filename"].endswith(".whl") for item in artifacts), 25)
        self.assertEqual([item["name"] for item in artifacts if item["artifact_type"] == "sdist"], ["psycopg2"])

    def test_wrong_official_hash_or_host_is_rejected_before_download(self):
        for field, value in (("sha256", "0" * 64), ("url", "https://example.org/package.whl")):
            metadata = json.loads(sandbox.METADATA.read_text())
            metadata["official_artifacts"][0][field] = value
            path = self.directory / (field + ".json")
            path.write_text(json.dumps(metadata))
            with self.subTest(field=field), patch.object(sandbox, "METADATA", path), self.assertRaisesRegex(ValueError, "disagree"):
                sandbox.pinned_artifacts()

    def test_repeated_lock_pin_is_rejected(self):
        path = self.directory / "repeated.lock"
        contents = sandbox.OFFICIAL_LOCK.read_text()
        path.write_text(contents + contents.splitlines()[0] + "\n")
        with patch.object(sandbox, "OFFICIAL_LOCK", path), self.assertRaisesRegex(ValueError, "repeats"):
            sandbox.pinned_artifacts()

    def test_unprepared_directory_cannot_start_adapter(self):
        (self.directory / "environment.json").write_text('{"status":"failed"}')
        with self.assertRaisesRegex(ValueError, "invalid"), patch.object(sandbox.subprocess, "Popen") as child:
            sandbox.run_once(self.directory, self.directory)
        child.assert_not_called()

    def test_nonobject_environment_is_rejected(self):
        (self.directory / "environment.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "invalid"):
            sandbox.prepared_environment(self.directory)

    def test_pip_environment_cannot_redirect_logs_or_installation(self):
        with patch.dict(sandbox.os.environ, {"PIP_LOG": "/outside/log", "PIP_TARGET": "/outside/site"}):
            cleaned = sandbox.clean_env()
            self.assertNotIn("PIP_LOG", cleaned)
            self.assertNotIn("PIP_TARGET", cleaned)
            self.assertEqual(cleaned["PIP_CONFIG_FILE"], sandbox.os.devnull)
            self.assertEqual(sandbox.os.environ["PIP_LOG"], "/outside/log")

    def test_root_is_rejected_before_inspection(self):
        with patch.object(sandbox.os, "geteuid", return_value=0), \
                patch.object(sandbox, "inspect") as inspection, self.assertRaisesRegex(ValueError, "non-root"):
            sandbox.doctor(self.directory, Path("/unused/python"), Path("/unused/pg"))
        inspection.assert_not_called()

    def test_missing_pg_selection_is_actionable_and_does_not_write(self):
        with patch.object(sandbox, "doctor") as doctor:
            self.assertEqual(sandbox.main(["doctor", "--output-parent", str(self.directory)]), 2)
        doctor.assert_not_called()
        self.assertEqual(list(self.directory.iterdir()), [])

    def fake_run(self, receipt_text, copies=1, exit_code=0):
        record = {"python": "/unused/python", "postgres_bin": "/unused/pg",
                  "installed": {}, "preflight": {"compiler": "/unused/cc"}}
        preflight = {"postgres_paths": {"libdir": "/unused/lib"}}
        def launch(command, **kwargs):
            self.assertEqual(command[2], str(sandbox.ROOT / "tools/run_contract.py"))
            parent = Path(command[-1])
            for number in range(copies):
                work = parent / ("schema-migration-new-" + str(number))
                work.mkdir()
                (work / "portable-run.json").write_text(receipt_text)
            child = unittest.mock.Mock()
            child.wait.return_value = exit_code
            return child
        with patch.object(sandbox, "prepared_environment", return_value=record), \
                patch.object(sandbox, "doctor", return_value=(preflight, self.directory)), \
                patch.object(sandbox, "inspect", return_value="{}"), \
                patch.object(sandbox.subprocess, "Popen", side_effect=launch) as child, \
                patch.dict(sys.modules, {"report": unittest.mock.Mock(write_report=unittest.mock.Mock(
                    return_value={"status": "consistent_record", "evidence_passed": True}))}):
            result = sandbox.run_once(self.directory, self.directory)
        self.assertEqual(child.call_count, 1)
        saved = json.loads((Path(result["run_parent"]) / "run-wrapper.json").read_text())
        self.assertEqual(saved, result)
        self.assertTrue((Path(result["run_parent"]) / "adapter.stdout.log").is_file())
        self.assertTrue((Path(result["run_parent"]) / "adapter.stderr.log").is_file())
        return result

    def test_wrapper_uses_its_one_new_receipt(self):
        stale = self.directory / "schema-migration-stale"
        stale.mkdir()
        (stale / "portable-run.json").write_text('{"status":"passed"}')
        result = self.fake_run('{"status":"passed"}')
        self.assertEqual(result["status"], "passed")
        self.assertNotIn("stale", result["portable_run"])

    def test_wrapper_does_not_accept_ambiguous_receipts(self):
        result = self.fake_run('{"status":"passed"}', copies=2)
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("portable_run", result)

    def test_wrapper_preserves_failed_adapter_exit(self):
        result = self.fake_run('{"status":"passed"}', exit_code=1)
        self.assertEqual(result["status"], "failed")

    def test_wrapper_preserves_malformed_receipt_as_failure(self):
        result = self.fake_run("{broken")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["report_status"], "failed")


if __name__ == "__main__":
    unittest.main()
