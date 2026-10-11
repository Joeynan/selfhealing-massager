import importlib.util, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]

class EntryTests(unittest.TestCase):
    def entry(self):
        path=ROOT/'tools/team_entry.py'
        self.assertTrue(path.is_file(),'Mac and Windows entries must use one resolver')
        spec=importlib.util.spec_from_file_location('team_entry',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    def test_offline_flash_does_not_require_installed_flash_environment(self):
        m=self.entry()
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(m.entry_python('flash',['--dry-run'],Path(temp)),Path(m.sys.executable))
    def test_flash_prefers_dedicated_environment(self):
        m=self.entry()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);python=m.flash_python(root);python.parent.mkdir(parents=True);python.touch()
            self.assertEqual(m.entry_python('flash',[],root),python)
    def test_missing_flash_environment_has_install_instruction(self):
        m=self.entry()
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError,'flash-only'):m.entry_python('flash',[],Path(temp))
    def test_entrypoint_maps_rollback_to_verified_release(self):
        m=self.entry()
        command=m.command_for('rollback',['--dry-run'],ROOT)
        self.assertIn('--rollback',command);self.assertEqual(command[-1],'--dry-run')

if __name__=='__main__':unittest.main()
