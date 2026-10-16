"""Inspect saved fixed-contract records without connecting to PostgreSQL."""
import argparse
from copy import deepcopy
import hashlib
from html import escape
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
OLD = ['sad', 'ok', 'happy']
EXPANDED = OLD + ['soso']
ROWS = [{'id': 1, 'mood': 'sad', 'payload': 'alpha'},
        {'id': 2, 'mood': 'ok', 'payload': 'beta'},
        {'id': 3, 'mood': 'happy', 'payload': 'gamma'}]
DRIFT = ('wrong_schema', 'wrong_type', 'wrong_table', 'wrong_gate',
         'contradictory_marker', 'changed_original_row', 'wrong_label_order')
INTERRUPTIONS = ('stop_before_expansion', 'stop_after_durable_expansion')
CASES = ('normal_and_old_clients',) + INTERRUPTIONS + DRIFT + ('activation_negative_control',)
SCOPE = ('This screen checks saved, editable records for one synthetic PostgreSQL contract. '
         'It does not run a database, probe current processes or authenticate the records. '
         'Worker SIGKILL is not power-loss recovery. The fixed old-client gate is not a '
         'distributed deployment protocol or a production availability guarantee. '
         'Use stable owner-controlled files; concurrent hostile filesystem changes are outside this check.')


def require(condition):
    if not condition:
        raise ValueError('Incomplete or inconsistent fixed-contract evidence')


def checked_path(path, directory=False):
    path = Path(path).expanduser().absolute()
    require('..' not in path.parts)
    for item in (path,) + tuple(path.parents):
        require(not item.is_symlink())
    require(path.is_dir() if directory else path.is_file())
    return path


def raw_file(path):
    path = checked_path(path)
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode))
        raw = stream.read(4_194_305)
    require(len(raw) <= 4_194_304)
    return raw


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def invalid_constant(_):
    raise ValueError('Non-finite JSON value')


def loads(raw):
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def state(value, labels, complete=False):
    require(value['schema_exists'] is True and value['labels'] == labels)
    require(value['marker'] == ([{'id': 1, 'completed': True}] if complete else []))
    require(all(type(row['id']) is int and row['completed'] is True for row in value['marker']))
    require([row for row in value['rows'] if row['id'] in (1, 2, 3)] == ROWS)
    require(all(row['mood'] in OLD and row['id'] != 999 for row in value['rows']))


def repeat(value):
    require(value['before_second'] == value['after_second'])
    require(value['resume']['after'] == value['before_second'])
    require(value['resume_again']['before'] == value['before_second'])
    require(value['resume_again']['after'] == value['after_second'])
    require(value['unchanged_sha256'] == digest(value['after_second']))
    state(value['after_second'], EXPANDED, True)
    require(value['resume']['status'] in ('completed', 'already_complete'))
    require(value['resume_again']['status'] == 'already_complete')
    require(value['resume_again']['events'] == [])


def old_client(value, row_id, reject=False):
    require(all(row[1] in OLD for row in value['read_before'] + value['read_after_insert_update']))
    require(value['read_after_insert_update'] == sorted(value['read_before'] + [[row_id, 'ok', 'old-client']], key=lambda row: row[0]))
    require([row for row in value['read_after_insert_update'] if row[0] == row_id] == [[row_id, 'ok', 'old-client']])
    require([[row['id'], row['mood'], row['payload']] for row in value['readback']['rows']] == value['read_after_insert_update'])
    require([row for row in value['readback']['rows'] if row['id'] in (1, 2, 3)] == ROWS)
    require(all(row['id'] != 999 for row in value['readback']['rows']))
    if reject:
        require(value['rejected_new_label'] == {'sqlstate': '23514', 'constraint': 'legacy_labels'})


def autocommit_events(value, module, sql):
    statements = [event for event in value['events'] if 'sql' in event]
    require(statements == [{'sql': sql, 'dbapi_autocommit': True}])
    frames = [event for event in value['events'] if 'autocommit_frame' in event]
    require([event['autocommit_frame'] for event in frames] == ['call', 'return', 'call', 'return'])
    require(all(Path(event['source']) == module / 'runtime/migration.py' for event in frames))
    require([event['barrier'] for event in value['events'] if 'barrier' in event] == ['before-expansion', 'after-marker-insert'])


def expected_drift(name, fixture):
    """Mirror only the seven fixed mutations in the preserved harness SQL."""
    expected = deepcopy(fixture)
    if name == 'wrong_schema':
        expected.update(schema_exists=False, shape={key: [] for key in fixture['shape']}, labels=[], rows=[])
    elif name == 'wrong_type':
        expected['shape']['type'] = [['d']]
        expected['shape']['columns'][1][2:5] = ['text', 'pg_catalog', 'text']
        expected['labels'] = []
    elif name == 'wrong_table':
        expected['shape']['columns'].insert(3, ['items', 'unexpected', 'integer', 'pg_catalog', 'int4', 'YES', '0'])
        expected['rows'] = [dict(row, unexpected=0) for row in ROWS]
    elif name == 'wrong_gate':
        expected['shape']['constraints'] = [row for row in fixture['shape']['constraints'] if row[1] != 'legacy_labels']
    elif name == 'contradictory_marker':
        expected['marker'] = [{'id': 1, 'completed': True}]
    elif name == 'changed_original_row':
        expected['rows'][1]['payload'] = 'changed'
    elif name == 'wrong_label_order':
        expected['labels'] = ['ok', 'sad', 'happy']
    else:
        raise ValueError('Unknown fixed drift case')
    return expected


def source_tree(directory, expected):
    directory = checked_path(directory, directory=True)
    live = {path.relative_to(directory).as_posix(): path for path in directory.rglob('*') if path.is_file()}
    require(set(live) == set(expected))
    for name, record in expected.items():
        raw = raw_file(live[name])
        require(len(raw) == record['bytes'] and hashlib.sha256(raw).hexdigest() == record['sha256'])


def inspect_run(run):
    review = {'schema_version': 1, 'status': 'not_consistent', 'evidence_passed': False,
              'input_record_sha256': '', 'checks': {}, 'cases': [], 'interruptions': [],
              'worker_count': 0, 'scope': SCOPE, 'failure_stage': 'adapter_record'}
    try:
        run = checked_path(run, directory=True)
        raw = raw_file(run / 'portable-run.json')
        review['input_record_sha256'] = hashlib.sha256(raw).hexdigest()
        portable = loads(raw)
        require(portable['status'] == 'passed' and type(portable['exit_code']) is int and portable['exit_code'] == 0)
        require(Path(portable['output']) == run and len(portable['receipts']) == 1)
        require(all(item['exit_code'] == 0 for item in portable['fallback_cleanup']))
        require(portable['versions']['python'] == '3.12.3')
        for pin in (ROOT / 'requirements.lock').read_text().splitlines():
            name, version = pin.split('==')
            require(portable['versions']['packages'][name.lower().replace('_', '-')] == version)
        receipt = checked_path(portable['receipts'][0])
        evidence = run / 'project/evidence'
        require(receipt.parent.parent == evidence and receipt.name == 'contract-result.json')
        contract = loads(raw_file(receipt))
        require(contract['status'] == 'passed' and set(contract['cases']) == set(CASES))
        require(contract['python'] == portable['python'])
        require(Path(contract['evidence']) == receipt.parent)
        require(Path(contract['native']).parent == run / 'native')
        require(Path(contract['cluster']) == Path(contract['native']) / 'pgdata')
        require(type(contract['port']) is int and 1 <= contract['port'] <= 65535)
        pg, cluster = Path(portable['postgres_bin']), contract['cluster']
        expected_commands = [[str(pg / 'initdb'), '-D', cluster, '-U', 'sql_rehearsal', '--auth=trust', '--no-locale', '--encoding=UTF8'],
            [str(pg / 'pg_ctl'), '-D', cluster, '-l', str(Path(contract['native']) / 'postgres.log'), '-o',
             f"-h 127.0.0.1 -p {contract['port']} -c unix_socket_directories= -c log_statement=all -c extension_control_path={portable['sharedir']}", '-w', 'start']]
        for name in ('normal',) + INTERRUPTIONS + DRIFT + ('activation_negative_control',):
            expected_commands.append([str(pg / 'createdb'), '-h', '127.0.0.1', '-p', str(contract['port']), '-U', 'sql_rehearsal', '-T', 'template0', name])
        expected_commands.append([str(pg / 'pg_ctl'), '-D', cluster, '-m', 'fast', '-w', 'stop'])
        require([row['command'] for row in contract['commands']] == expected_commands)
        require(all(type(row['exit_code']) is int and row['exit_code'] == 0 for row in contract['commands']))
        review['checks']['complete_adapter_and_profile'] = True
        review['failure_stage'] = 'preserved_source'
        manifest_raw = raw_file(ROOT / 'source-copy-manifest.json')
        require(raw_file(evidence / 'source-manifest.json') == manifest_raw)
        manifest = loads(manifest_raw)
        for label in ('original', 'components'):
            source_tree(run / 'project' / label / 'alembic', manifest['source_files'])
        source_tree(run / 'project/rehearsal', manifest['protected_rehearsal_files'])
        require(contract['source_unchanged'] == {'original': True, 'components': True})
        require(contract['extension_body_sha256'] == {name: row['sha256'] for name, row in manifest['protected_rehearsal_files'].items()})
        review['checks']['materialized_source_bytes'] = True
        review['failure_stage'] = 'scenario_records'
        cases = contract['cases']
        normal = cases['normal_and_old_clients']
        state(normal['fixture'], OLD)
        require(normal['old_before']['read_before'] == [[row['id'], row['mood'], row['payload']] for row in normal['fixture']['rows']])
        old_client(normal['old_before'], 100)
        old_client(normal['old_after'], 101, True)
        require(normal['expansion']['before'] == normal['old_before']['readback'])
        require(normal['old_after']['readback'] == normal['repeat']['before_second'])
        state(normal['expansion']['after'], EXPANDED, True)
        require(normal['old_after']['read_before'] == [[row['id'], row['mood'], row['payload']] for row in normal['expansion']['after']['rows']])
        repeat(normal['repeat'])
        expected_workers = {'normal-expansion': (0, normal['expansion']),
                            'normal-resume': (0, normal['repeat']['resume']),
                            'normal-resume-again': (0, normal['repeat']['resume_again'])}
        for name in INTERRUPTIONS:
            case = cases[name]
            labels = OLD if name == 'stop_before_expansion' else EXPANDED
            state(case['fresh_at_barrier'], labels)
            state(case['fresh_after_kill'], labels)
            require(case['fresh_after_kill'] == case['old_during_barrier']['readback'])
            require(case['termination']['signal'] == 'SIGKILL' and case['termination']['exit_code'] == -9)
            require(case['worker_at_barrier']['status'] == 'running')
            if name == 'stop_before_expansion':
                require(case['worker_at_barrier']['events'] == [{'barrier': 'before-expansion'}])
                require(case['worker_at_barrier']['before'] == case['fresh_at_barrier'])
            if name == 'stop_after_durable_expansion':
                state(case['worker_at_barrier']['before'], OLD)
                require(case['worker_at_barrier']['expanded'] == case['fresh_at_barrier'])
                autocommit_events(case['worker_at_barrier'], run / 'project/components/alembic/alembic',
                                  (run / 'project/rehearsal/expand.sql').read_text())
                require(case['worker_at_barrier']['marker_visible_inside_worker_transaction'] == [{'id': 1, 'completed': True}])
            old_client(case['old_during_barrier'], 100, name == 'stop_after_durable_expansion')
            require(case['old_during_barrier']['read_before'] == [[row['id'], row['mood'], row['payload']] for row in case['fresh_at_barrier']['rows']])
            repeat(case['resumption'])
            require(case['resumption']['resume']['before'] == case['fresh_after_kill'])
            require(case['resumption']['resume']['status'] == 'completed')
            expected_workers.update({name: (-9, case['worker_at_barrier']),
                                     name + '-resume': (0, case['resumption']['resume']),
                                     name + '-resume-again': (0, case['resumption']['resume_again'])})
            review['interruptions'].append({'case': name, 'labels_after_kill': labels,
                'marker_after_kill': False, 'worker_exit': -9, 'resumed': True, 'second_resume_unchanged': True})
        for name in DRIFT:
            case = cases[name]
            require(case['before'] == case['after'] and case['state_sha256'] == digest(case['after']))
            require(case['rejected']['status'] == 'state_drift' and case['rejected']['events'] == [])
            require(set(case['before']) == set(normal['fixture']) and case['rejected']['before'] == case['before'])
            require(set(case['before']['shape']) == set(normal['fixture']['shape']))
            require(type(case['before']['schema_exists']) is bool)
            require(case['before'] == expected_drift(name, normal['fixture']))
            require(case['renamed_schema_rows'] == (ROWS if name == 'wrong_schema' else None))
            expected_workers[name] = (1, case['rejected'])
        activation = cases['activation_negative_control']
        require(activation['expanded']['status'] == 'completed')
        require(all(row[1] in OLD for row in activation['old_read_before']))
        require(activation['old_read_before'] == [[row['id'], row['mood'], row['payload']] for row in activation['expanded']['after']['rows']])
        activated = activation['activated_readback']
        require(activated['labels'] == EXPANDED and activated['marker'] == [{'id': 1, 'completed': True}])
        require({'id': 200, 'mood': 'soso', 'payload': 'explicit-activation'} in activated['rows'])
        require(activated['rows'] == ROWS + [{'id': 200, 'mood': 'soso', 'payload': 'explicit-activation'}])
        before_shape = activation['expanded']['after']['shape']
        require({key: value for key, value in activated['shape'].items() if key != 'constraints'} ==
                {key: value for key, value in before_shape.items() if key != 'constraints'})
        require(activated['shape']['constraints'] == [row for row in before_shape['constraints'] if row[1] != 'legacy_labels'])
        require(activation['old_reader_failure'] == "Old reader rejects stored label 'soso' at row 200")
        expected_workers['activation-expansion'] = (0, activation['expanded'])
        require(len(contract['workers']) == len(expected_workers) == 17)
        require({row['name'] for row in contract['workers']} == set(expected_workers))
        for worker in contract['workers']:
            name = worker['name']
            code, embedded = expected_workers[name]
            require(type(worker['exit_code']) is int and worker['exit_code'] == code)
            require(Path(worker['out']) == receipt.parent / (name + '.json'))
            require(loads(raw_file(worker['out'])) == embedded)
            module = run / 'project/components/alembic/alembic'
            require(Path(embedded['source']) == module / 'runtime/migration.py')
            require(Path(embedded['alembic_file']) == module / '__init__.py')
            require(Path(embedded['unwrapped_code_source']) == module / 'runtime/migration.py')
            require(embedded['source_sha256'] == manifest['source_files']['alembic/runtime/migration.py']['sha256'])
            if embedded['status'] == 'completed':
                require(embedded['before']['labels'] in (OLD, EXPANDED))
                state(embedded['before'], embedded['before']['labels'])
                state(embedded['expanded'], EXPANDED)
                state(embedded['after'], EXPANDED, True)
                require(embedded['before']['rows'] == embedded['expanded']['rows'] == embedded['after']['rows'])
                require(embedded['before']['shape'] == embedded['expanded']['shape'] == embedded['after']['shape'] == normal['fixture']['shape'])
                require(embedded['marker_visible_inside_worker_transaction'] == [{'id': 1, 'completed': True}])
                autocommit_events(embedded, module, (run / 'project/rehearsal/expand.sql').read_text())
            elif embedded['status'] == 'already_complete':
                require(embedded['events'] == [] and embedded['before'] == embedded['after'])
                state(embedded['before'], EXPANDED, True)
                require(embedded['before']['shape'] == normal['fixture']['shape'])
        review['checks']['eleven_cases_and_seventeen_workers'] = True
        review['failure_stage'] = 'recorded_cleanup'
        require(type(contract['final']['pg_ctl_status']) is int)
        require(all(type(contract['final'][key]) is bool for key in ('postmaster_pid_exists', 'port_open', 'workers_stopped', 'all_stopped')))
        require(contract['final'] == {'pg_ctl_status': 3, 'postmaster_pid_exists': False,
                'port_open': False, 'workers_stopped': True, 'all_stopped': True})
        review['checks']['recorded_cluster_and_worker_cleanup'] = True
        review['cases'] = [{'case': name, 'outcome': 'Expected rejection' if name in DRIFT else
                          ('Expected old-reader incompatibility' if name == 'activation_negative_control' else 'Completed with compatible old-client operations')}
                          for name in CASES]
        review.update(status='consistent_record', evidence_passed=True, worker_count=17, failure_stage=None)
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
        review['checks']['complete_consistent_evidence'] = False
        review['cases'], review['interruptions'] = [], []
    return review


def render(review):
    passed = review['evidence_passed']
    heading = '11 recorded scenarios passed' if passed else 'Saved result is incomplete or inconsistent'
    cases = ''.join('<tr><th scope="row">' + escape(row['case'].replace('_', ' ')) + '</th><td>' + escape(row['outcome']) + '</td></tr>' for row in review['cases'])
    interruptions = ''.join('<tr><th scope="row">' + escape(row['case'].replace('_', ' ')) + '</th><td>' + escape(', '.join(row['labels_after_kill'])) + '</td><td>No committed marker</td><td>SIGKILL / -9</td><td>Completed; second resume unchanged</td></tr>' for row in review['interruptions'])
    checks = ''.join('<tr><th scope="row">' + escape(name.replace('_', ' ')) + '</th><td>' + ('Passed' if value else 'Failed / missing') + '</td></tr>' for name, value in review['checks'].items())
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>Schema migration rehearsal result</title><style>
body{{margin:0;font:16px/1.65 system-ui,sans-serif;color:#182736;background:#f4f7fb}}main{{max-width:72rem;margin:auto;padding:2rem 1rem}}h1,h2{{line-height:1.3}}p{{max-width:80ch}}.panel{{padding:1.5rem;margin:1rem 0;background:white;border:1px solid #cfdae7;border-radius:.5rem}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:40rem}}th,td{{padding:.7rem;text-align:left;vertical-align:top;border-bottom:1px solid #cfdae7}}thead{{background:#e9f1f8}}code{{overflow-wrap:anywhere}}a{{color:#075f8c}}summary{{cursor:pointer;font-weight:600}}:focus-visible{{outline:3px solid #2574ac;outline-offset:3px}}@media(max-width:600px){{main{{padding:1rem .7rem}}.panel{{padding:1rem}}[aria-label="Recorded scenarios"] table,[aria-label="Evidence checks"] table{{min-width:0}}[aria-label="Recorded scenarios"] th{{width:45%}}[aria-label="Evidence checks"] th{{width:70%}}}}@media print{{body{{background:white}}main{{max-width:none;padding:0}}.panel{{break-inside:avoid}}.scroll{{overflow:visible}}table{{min-width:0}}}}@media(prefers-reduced-motion:reduce){{*{{scroll-behavior:auto}}}}
</style></head><body><main><h1>Schema migration rehearsal</h1><p>A local, synthetic enum migration. This offline screen reads saved records and starts no database or worker.</p>
<section class="panel"><h2>{heading}</h2><p>{'Seventeen recorded worker exits match the fixed contract: two deliberately killed workers, seven drift rejections and eight normal completions. The saved records include cluster shutdown and unchanged source copies.' if passed else 'No partial scenario is presented as an overall pass. Inspect the original run directory and repair the missing or contradictory evidence before generating a new report.'}</p><p>Expansion makes a new enum label durable before the completion marker commits. A separate table gate keeps the older client within its accepted labels until explicit activation.</p></section>
<section class="panel"><h2>What survives a worker interruption?</h2><p>A fresh connection sees the committed enum labels and no completion marker. Resume completes the marker; repeating it leaves the full snapshot unchanged. On small screens, scroll this wide table horizontally to inspect the later columns.</p><div class="scroll" role="region" aria-label="Interruption and resumption" tabindex="0"><table><thead><tr><th>Interruption</th><th>Labels after kill</th><th>Completion</th><th>Worker exit</th><th>Resume</th></tr></thead><tbody>{interruptions}</tbody></table></div></section>
<section class="panel"><h2>Expected outcomes</h2><p>Drift rejection and the final old-reader failure are deliberate controls. Keeping old-client writes compatible before activation does not make the new label compatible after activation.</p><div class="scroll" role="region" aria-label="Recorded scenarios" tabindex="0"><table><thead><tr><th>Scenario</th><th>Observed outcome</th></tr></thead><tbody>{cases}</tbody></table></div></section>
<details class="panel"><summary>Evidence checks and recorded cleanup</summary><div class="scroll" role="region" aria-label="Evidence checks" tabindex="0"><table><thead><tr><th>Check</th><th>Result</th></tr></thead><tbody>{checks}</tbody></table></div><p>Adapter record SHA-256: <code>{escape(review['input_record_sha256'])}</code></p><p><a href="review.json">Portable review JSON</a>. Raw records remain in the original run and can contain machine paths and local connection details.</p></details>
<section class="panel"><h2>Scope and limits</h2><p>{escape(SCOPE)}</p><p>Focus wide tables to scroll with a keyboard. There are no external fonts, scripts or network resources.</p></section></main></body></html>'''


def summary_text(review):
    lines = ['Schema Migration Rehearsal: ' + review['status']]
    if review['evidence_passed']:
        lines += ['11 scenarios; 17 worker exits; recorded cluster and worker cleanup passed.',
                  'Expected controls: 2 SIGKILL exits, 7 drift rejections, 1 old-reader incompatibility.']
        for case in review['interruptions']:
            lines.append(case['case'] + ': labels=' + ','.join(case['labels_after_kill']) +
                         '; marker absent after kill; resume completed; second resume unchanged.')
    else:
        lines.append('FAILED at ' + str(review.get('failure_stage')) +
                     '. Inspect the original run and adapter/harness logs; no overall pass is available.')
    lines += ['', 'Scenarios:'] + [row['case'] + ': ' + row['outcome'] for row in review['cases']]
    lines += ['', 'Checks:'] + [name + ': ' + ('passed' if value else 'failed/missing')
                               for name, value in review['checks'].items()]
    lines += ['', 'Adapter record SHA-256: ' + review['input_record_sha256'], '', review['scope']]
    return '\n'.join(lines) + '\n'


def write_report(run, output):
    run = checked_path(run, directory=True)
    output = Path(output).expanduser().absolute()
    checked_path(output.parent, directory=True)
    require('..' not in output.parts and not os.path.lexists(output))
    require(not output.is_relative_to(ROOT) and not output.is_relative_to(run / 'project')
            and not output.is_relative_to(run / 'native') and not run.is_relative_to(output))
    review = inspect_run(run)
    output.mkdir(mode=0o700)
    for name, value in (('review.json', json.dumps(review, indent=2, allow_nan=False) + '\n'),
                        ('report.html', render(review)), ('summary.txt', summary_text(review))):
        with os.fdopen(os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600), 'w', encoding='utf-8') as stream:
            stream.write(value)
    return review


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--output', type=Path, help='Optional new output directory; omit for read-only terminal inspection')
    parser.add_argument('--json', action='store_true', help='Print review JSON instead of the terminal summary')
    args = parser.parse_args(argv)
    try:
        review = write_report(args.run, args.output) if args.output else inspect_run(args.run)
    except (OSError, ValueError, TypeError, RecursionError):
        print('Invalid input/output; existing files were not replaced.', file=sys.stderr)
        return 2
    print(json.dumps(review, indent=2) if args.json else summary_text(review), end='\n' if args.json else '')
    return 0 if review['evidence_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
