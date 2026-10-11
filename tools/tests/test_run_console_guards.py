"""The offline test guard remains subclassable on Windows, but cannot spawn."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class ConsoleGuardTests(unittest.TestCase):
    def test_lazy_windows_popen_subclass_still_rejects_real_children(self):
        driver = r"""
import importlib.util, inspect, subprocess, sys, unittest
from pathlib import Path
root = Path(sys.argv[2])
(root/'outputs/Watcher\u63a7\u5236\u53f0').mkdir(parents=True)
spec = importlib.util.spec_from_file_location('guarded_console', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
module.ROOT = root
def check_guard():
    assert inspect.isclass(subprocess.Popen), 'Windows asyncio requires a subclassable Popen class'
    class LazyWindowsPopen(subprocess.Popen): pass
    try:
        LazyWindowsPopen(['this-process-must-never-start'])
    except AssertionError as exc:
        assert 'mocked' in str(exc)
    else:
        raise AssertionError('The test guard permitted an unmocked child process')
unittest.defaultTestLoader.discover = lambda *a, **k: unittest.TestSuite([unittest.FunctionTestCase(check_guard)])
raise SystemExit(module.main())
"""
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, '-c', driver, str(ROOT/'tools/run_console_tests.py'), folder],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding='utf-8', timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == '__main__': unittest.main()
