"""Operation boundaries: inspection writes nothing; cleanup selects only owned runs."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report, sandbox = load('report'), load('sandbox')


@unittest.skipUnless(sys.platform == 'linux', 'Native Linux operation boundaries')
class OperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='schema-operations-')
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.run = self.parent / 'schema-run-abcdefgh'
        self.run.mkdir()
        self.owner = {'product': 'schema-migration-rehearsal', 'kind': 'run',
                      'run_parent': str(self.run), 'ownership_token': 'a' * 32}
        self.receipt = {'run_parent': str(self.run), 'ownership_token': 'a' * 32, 'adapter_invocations': 1}
        (self.run / 'schema-migration-example').mkdir()
        (self.run / 'adapter.stdout.log').touch()
        (self.run / 'adapter.stderr.log').touch()
        self.save()

    def save(self):
        (self.run / 'run-owner.json').write_text(json.dumps(self.owner))
        (self.run / 'run-wrapper.json').write_text(json.dumps(self.receipt))

    def test_inspection_is_read_only_and_failed_record_is_not_a_pass(self):
        before = sorted(str(path) for path in self.run.rglob('*'))
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(report.main(['--run', str(self.run)]), 1)
        self.assertEqual(before, sorted(str(path) for path in self.run.rglob('*')))
        self.assertIn('FAILED at adapter_record', output.getvalue())

    def test_cleanup_requires_explicit_remove_and_keeps_environment(self):
        environment = self.parent / 'environment'
        environment.mkdir()
        self.assertEqual(sandbox.cleanup_run(self.run)['status'], 'cleanup_ready')
        self.assertTrue(self.run.exists())
        self.assertEqual(sandbox.cleanup_run(self.run, True)['status'], 'removed')
        self.assertFalse(self.run.exists())
        self.assertTrue(environment.exists())

    def test_parent_or_environment_cannot_be_cleanup_target(self):
        for path in (self.parent, self.parent / 'environment'):
            path.mkdir(exist_ok=True)
            with self.subTest(path=path), self.assertRaises(ValueError):
                sandbox.cleanup_run(path, True)
            self.assertTrue(path.exists())

    def test_foreign_or_changed_ownership_is_refused(self):
        for key, value in (('ownership_token', 'b' * 32), ('run_parent', str(self.parent))):
            receipt = dict(self.receipt, **{key: value})
            (self.run / 'run-wrapper.json').write_text(json.dumps(receipt))
            with self.subTest(key=key), self.assertRaises(ValueError):
                sandbox.cleanup_run(self.run, True)
            self.assertTrue(self.run.exists())

    def test_symlink_or_unrecognized_content_is_refused(self):
        foreign = self.parent / 'keep.txt'
        foreign.write_text('keep')
        alias = self.run / 'alias'
        alias.symlink_to(foreign)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            sandbox.cleanup_run(self.run, True)
        alias.unlink()
        (self.run / 'foreign.txt').touch()
        with self.assertRaisesRegex(ValueError, 'Unrecognized'):
            sandbox.cleanup_run(self.run, True)
        self.assertEqual(foreign.read_text(), 'keep')

    def test_nested_symlink_and_pid_refuse_removal(self):
        cluster = self.run / 'schema-migration-example' / 'pgdata'
        cluster.mkdir()
        alias = cluster / 'alias'
        alias.symlink_to(self.parent)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            sandbox.cleanup_run(self.run, True)
        alias.unlink()
        (cluster / 'postmaster.pid').write_text('123')
        with self.assertRaisesRegex(ValueError, 'postmaster.pid'):
            sandbox.cleanup_run(self.run, True)
        self.assertTrue(cluster.exists())

    def test_unreadable_nested_subtree_refuses_before_any_removal(self):
        inaccessible = self.run / 'schema-migration-example' / 'pgdata' / 'inaccessible'
        inaccessible.mkdir(parents=True)
        (inaccessible / 'postmaster.pid').write_text('123\n')
        (inaccessible / 'keep.bin').write_bytes(b'preserve all evidence\x00\xff')
        before = {path.relative_to(self.run).as_posix(): path.read_bytes()
                  for path in self.run.rglob('*') if path.is_file()}
        for remove in (False, True):
            with self.subTest(remove=remove):
                inaccessible.chmod(0)
                try:
                    with self.assertRaises(PermissionError):
                        list(inaccessible.iterdir())
                    with self.assertRaisesRegex(ValueError, 'cannot be fully inspected'):
                        sandbox.cleanup_run(self.run, remove)
                finally:
                    inaccessible.chmod(0o700)
                after = {path.relative_to(self.run).as_posix(): path.read_bytes()
                         for path in self.run.rglob('*') if path.is_file()}
                self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
