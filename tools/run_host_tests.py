#!/usr/bin/env python3
"""Build/run the available persisted host tests; never access hardware."""
from pathlib import Path
import argparse
import datetime
import hashlib
import subprocess

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / 'work'
CONSOLE = ROOT / 'outputs/Watcher控制台'
TESTS = CONSOLE / 'tests'
BUILD = ROOT / 'work/host-tests'
REPORT = ROOT / 'work/team-validation/host-tests.md'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only-json', action='store_true', help='Run only the newly available cJSON-dependent tests and retain prior results.')
    args = parser.parse_args()
    BUILD.mkdir(exist_ok=True)
    report = [f'Host regression run: {datetime.datetime.now().astimezone().isoformat()}',
              f'Source directory: {CONSOLE}',
              'No device enumeration, serial connection, firmware flashing or motor output was performed.',
              'The preserved tests are executed without rewriting their source.', '']
    results = []
    if args.only_json:
        # Reuse the recorded results of the previous run, not unexecuted claims.
        prior = REPORT.read_text()
        lines = prior.splitlines()
        for i, line in enumerate(lines):
            for state in ('PASS', 'COMPILE FAILED', 'RUN FAILED', 'NOT COVERED'):
                marker = ': ' + state
                if line.endswith(marker):
                    name = line[:-len(marker)]
                    evidence = []
                    j = i + 1
                    while j < len(lines) and lines[j]:
                        evidence.append(lines[j]); j += 1
                    if name not in ('landmark_decoder_test', 'vision_transport_test', 'wifi_decoder_test'):
                        results.append((name, state, '\n'.join(evidence)))
                    break
        report.insert(2, 'Non-JSON tests retain the preceding verified run recorded in host-tests.txt; only JSON-dependent tests were rerun at the time above.')
    cjson = None
    for root in [CACHE / 'xiaozhi-esp32', CACHE / 'esp-idf']:
        if root.exists():
            for candidate in root.rglob('cJSON.c'):
                if candidate.is_file() and (candidate.parent / 'cJSON.h').exists():
                    cjson = candidate
                    break
        if cjson:
            break
    cjson_obj = BUILD / 'cJSON.o'
    if cjson:
        compile_cjson = subprocess.run(['clang', '-std=c99', '-c', str(cjson), '-o', str(cjson_obj)], text=True, capture_output=True)
        (BUILD / 'cJSON.compile.log').write_text(compile_cjson.stdout + compile_cjson.stderr)
        if compile_cjson.returncode:
            report.append('cJSON dependency compilation failed: ' + compile_cjson.stderr.strip())
            cjson = None
        else:
            report.append(f'Fixed SDK cJSON: {cjson}; SHA256 {hashlib.sha256(cjson.read_bytes()).hexdigest()}')
    for source in sorted(TESTS.glob('*_test.cpp')):
        name = source.stem
        needs_json = name in ('landmark_decoder_test', 'vision_transport_test', 'wifi_decoder_test')
        if args.only_json and not needs_json:
            continue
        if needs_json and not cjson:
            results.append((name, 'NOT COVERED', 'fixed SDK cJSON source not available'))
            continue
        binary = BUILD / name
        command = ['clang++', '-std=c++17', '-Wall', '-Wextra', '-I' + str(CONSOLE / 'firmware/watcher-service'), '-I' + str(TESTS / 'node_stubs'), str(source)]
        if name == 'vision_transport_test':
            command += [str(CONSOLE / 'firmware/watcher-vision/src/landmark_message.cc'),
                        str(CONSOLE / 'firmware/watcher-vision/src/hand_geometry.cc')]
        if needs_json:
            command += ['-I' + str(cjson.parent), str(cjson_obj)]
        command += ['-o', str(binary)]
        compiled = subprocess.run(command, text=True, capture_output=True)
        log = compiled.stdout + compiled.stderr
        if compiled.returncode:
            results.append((name, 'COMPILE FAILED', log.strip()))
        else:
            run = subprocess.run([str(binary)], text=True, capture_output=True)
            log += '\n' + run.stdout + run.stderr
            results.append((name, 'PASS' if run.returncode == 0 else 'RUN FAILED', (run.stdout + run.stderr).strip() or f'exit={run.returncode}'))
        (BUILD / (name + '.log')).write_text(log)
        print(name + ': ' + results[-1][1], flush=True)
    for missing in ['node_portal_test', 'node_deadline_test']:
        if not (TESTS / (missing + '.cpp')).exists() and not any(r[0] == missing for r in results):
            results.append((missing, 'NOT COVERED', 'test source not present in persisted console'))
    for name, status, evidence in results:
        report += [f'{name}: {status}', evidence, '']
    passed = sum(r[1] == 'PASS' for r in results)
    failed = sum(r[1] in ('COMPILE FAILED', 'RUN FAILED') for r in results)
    skipped = sum(r[1] == 'NOT COVERED' for r in results)
    report += [f'Summary: {passed} passed, {failed} failed, {skipped} not covered.',
               'These are host simulations/unit tests. They do not prove physical power transitions, animation smoothness, real gesture accuracy, motor motion or stopping.']
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text('\n'.join(report) + '\n')
    (BUILD / 'summary.txt').write_text('\n'.join(report) + '\n')
    print(report[-2], flush=True)
    return failed

if __name__ == '__main__':
    raise SystemExit(main())
