"""Exercise saved-record corruption and output safety, without starting a database."""
import importlib.util
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('schema_report', ROOT / 'tools/report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class ParserAndRenderingTests(unittest.TestCase):
    def test_duplicate_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            report.loads('{"status":true,"status":false}')

    def test_nonfinite_value_is_rejected(self):
        with self.assertRaises(ValueError):
            report.loads('{"value":NaN}')

    def test_record_strings_are_escaped(self):
        review = {'evidence_passed': False, 'cases': [{'case': '<script>alert(1)</script>', 'outcome': '<img onerror="bad">'}],
                  'interruptions': [], 'checks': {}, 'input_record_sha256': '<script>bad</script>'}
        html = report.render(review)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img onerror=', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('Saved result is incomplete or inconsistent', html)


@unittest.skipUnless(os.environ.get('SCHEMA_RECORDED_RUN'), 'Set SCHEMA_RECORDED_RUN to an actual completed native run')
class RecordedContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / 'run'
        original = Path(os.environ['SCHEMA_RECORDED_RUN'])
        shutil.copytree(original / 'project', self.run / 'project')
        (self.run / 'native').mkdir()

        def rebase(value):
            if isinstance(value, str):
                return value.replace(str(original), str(self.run))
            if isinstance(value, list):
                return [rebase(item) for item in value]
            if isinstance(value, dict):
                return {key: rebase(item) for key, item in value.items()}
            return value

        self.save(self.run / 'portable-run.json', rebase(json.loads((original / 'portable-run.json').read_text())))
        for path in (self.run / 'project/evidence').glob('rollout-*/*.json'):
            self.save(path, rebase(json.loads(path.read_text())))
        self.contract_path = Path(json.loads((self.run / 'portable-run.json').read_text())['receipts'][0])
        self.contract = json.loads(self.contract_path.read_text())

    @staticmethod
    def save(path, value):
        path.write_text(json.dumps(value, indent=2) + '\n')

    def inspect(self, changed=True):
        if changed:
            self.save(self.contract_path, self.contract)
        return report.inspect_run(self.run)

    def rewrite_worker(self, name, record):
        self.save(self.contract_path.parent / (name + '.json'), record)

    def test_actual_record_has_eleven_cases_and_seventeen_workers(self):
        result = self.inspect(False)
        self.assertTrue(result['evidence_passed'])
        self.assertEqual(len(result['cases']), 11)
        self.assertEqual(result['worker_count'], 17)

    def test_expected_kill_cannot_be_relabelled_as_success(self):
        self.contract['workers'][3]['exit_code'] = 0
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_durable_label_cannot_disappear_after_kill(self):
        self.contract['cases']['stop_after_durable_expansion']['fresh_after_kill']['labels'] = report.OLD
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_uncommitted_marker_cannot_be_reported_as_committed(self):
        self.contract['cases']['stop_after_durable_expansion']['fresh_after_kill']['marker'] = [{'id': 1, 'completed': True}]
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_changed_second_resume_is_rejected_even_with_recomputed_digest(self):
        case = self.contract['cases']['normal_and_old_clients']['repeat']
        case['after_second']['rows'][0]['payload'] = 'unexpected'
        case['unchanged_sha256'] = report.digest(case['after_second'])
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_drift_must_reject_before_autocommit_events(self):
        case = self.contract['cases']['wrong_gate']['rejected']
        case['events'] = [{'sql': 'alter type'}]
        self.rewrite_worker('wrong_gate', case)
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_missing_case_is_not_an_overall_pass(self):
        del self.contract['cases']['wrong_type']
        result = self.inspect()
        self.assertFalse(result['evidence_passed'])
        self.assertEqual(result['cases'], [])

    def test_empty_drift_snapshots_cannot_pass_with_recomputed_digest(self):
        case = self.contract['cases']['wrong_gate']
        case['before'], case['after'] = {}, {}
        case['state_sha256'] = report.digest({})
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_already_complete_worker_requires_before_and_after(self):
        case = self.contract['cases']['normal_and_old_clients']['repeat']['resume']
        del case['before'], case['after']
        self.rewrite_worker('normal-resume', case)
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_empty_command_list_is_not_a_completed_adapter(self):
        self.contract['commands'] = []
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_activation_cannot_remove_original_rows(self):
        case = self.contract['cases']['activation_negative_control']
        case['activated_readback']['rows'] = [{'id': 200, 'mood': 'soso', 'payload': 'explicit-activation'}]
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_interrupted_worker_requires_its_recorded_barrier(self):
        case = self.contract['cases']['stop_before_expansion']['worker_at_barrier']
        case['events'] = []
        self.rewrite_worker('stop_before_expansion', case)
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_healthy_fixture_cannot_be_labelled_as_any_named_drift(self):
        original = deepcopy(self.contract)
        for name in report.DRIFT:
            with self.subTest(case=name):
                self.contract = deepcopy(original)
                case = self.contract['cases'][name]
                healthy = deepcopy(self.contract['cases']['normal_and_old_clients']['fixture'])
                case.update(before=healthy, after=deepcopy(healthy), state_sha256=report.digest(healthy))
                case['rejected']['before'] = deepcopy(healthy)
                self.rewrite_worker(name, case['rejected'])
                try:
                    self.assertFalse(self.inspect()['evidence_passed'])
                finally:
                    self.rewrite_worker(name, original['cases'][name]['rejected'])
        self.contract = original

    def test_second_resume_worker_cannot_disagree_with_fresh_snapshots(self):
        value = self.contract['cases']['normal_and_old_clients']['repeat']['resume_again']
        for key in ('before', 'after'):
            next(row for row in value[key]['rows'] if row['id'] == 100)['payload'] = 'forged'
        self.rewrite_worker('normal-resume-again', value)
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_first_resume_worker_cannot_disagree_with_fresh_snapshots(self):
        value = self.contract['cases']['normal_and_old_clients']['repeat']['resume']
        for key in ('before', 'after'):
            next(row for row in value[key]['rows'] if row['id'] == 100)['payload'] = 'forged'
        self.rewrite_worker('normal-resume', value)
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_resumed_interruption_worker_must_match_fresh_snapshots(self):
        value = self.contract['cases']['stop_after_durable_expansion']['resumption']['resume_again']
        for key in ('before', 'after'):
            next(row for row in value[key]['rows'] if row['id'] == 100)['payload'] = 'forged'
        self.rewrite_worker('stop_after_durable_expansion-resume-again', value)
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_changed_source_is_rejected(self):
        path = self.run / 'project/components/alembic/alembic/runtime/migration.py'
        path.write_bytes(path.read_bytes() + b'\n# changed\n')
        self.assertFalse(self.inspect(False)['evidence_passed'])

    def test_changed_sql_is_rejected(self):
        path = self.run / 'project/rehearsal/expand.sql'
        path.write_text('SELECT 1;')
        self.assertFalse(self.inspect(False)['evidence_passed'])

    def test_missing_worker_file_is_rejected(self):
        (self.contract_path.parent / 'normal-expansion.json').unlink()
        self.assertFalse(self.inspect(False)['evidence_passed'])

    def test_worker_file_must_equal_embedded_record(self):
        path = self.contract_path.parent / 'normal-expansion.json'
        value = json.loads(path.read_text())
        value['status'] = 'already_complete'
        self.save(path, value)
        self.assertFalse(self.inspect(False)['evidence_passed'])

    def test_rehashed_worker_still_requires_autocommit(self):
        value = self.contract['cases']['normal_and_old_clients']['expansion']
        for event in value['events']:
            if 'sql' in event:
                event['dbapi_autocommit'] = False
        self.rewrite_worker('normal-expansion', value)
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_open_listener_contradicts_cleanup(self):
        self.contract['final']['port_open'] = True
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_numeric_cleanup_flag_is_not_a_boolean_result(self):
        self.contract['final']['port_open'] = 0
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_numeric_completion_marker_is_not_a_boolean_result(self):
        self.contract['cases']['normal_and_old_clients']['expansion']['after']['marker'][0]['completed'] = 1
        self.rewrite_worker('normal-expansion', self.contract['cases']['normal_and_old_clients']['expansion'])
        self.assertFalse(self.inspect()['evidence_passed'])

    def test_worker_symlink_cannot_read_external_record(self):
        path = self.contract_path.parent / 'normal-expansion.json'
        external = Path(self.temp.name) / 'external.json'
        shutil.copyfile(path, external)
        path.unlink()
        path.symlink_to(external)
        self.assertFalse(self.inspect(False)['evidence_passed'])

    def test_existing_output_is_preserved(self):
        output = self.run / 'report'
        result = report.write_report(self.run, output)
        self.assertTrue(result['evidence_passed'])
        before = {path.name: path.read_bytes() for path in output.iterdir()}
        with self.assertRaises(ValueError):
            report.write_report(self.run, output)
        self.assertEqual(before, {path.name: path.read_bytes() for path in output.iterdir()})

    def test_report_cannot_write_inside_preserved_project(self):
        with self.assertRaises(ValueError):
            report.write_report(self.run, self.run / 'project/report')


if __name__ == '__main__':
    unittest.main()
