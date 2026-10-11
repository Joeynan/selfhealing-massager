import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launch


class LaunchTests(unittest.TestCase):
    def test_camera_owner_requires_explicit_diagnostic_flag(self):
        self.assertFalse(launch.parse_options([]).mac_camera)
        self.assertTrue(launch.parse_options(['--mac-camera']).mac_camera)

    def test_service_startup_timeout_is_an_error(self):
        with patch.object(launch, 'application', return_value=None), patch.object(launch.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, '启动超时'):
                launch.wait_ready(8877, 'watcher-handnodes', type('Child', (), {'poll': lambda _: None})(), 2, .5)

    def test_first_available_runtime_is_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder)/'first', Path(folder)/'second'
            second.touch()
            self.assertEqual(launch.select_python([first, second]), second)
            first.touch()
            self.assertEqual(launch.select_python([first, second]), first)

    def test_saved_hand_calibration_seeds_a_new_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            saved=Path(folder)/'saved.json';target=Path(folder)/'data/config.json'
            saved.write_text('{"folded_angle":149,"back_sign_by_hand":{"Left":0,"Right":1}}')
            launch.prepare_camera_config(saved,target)
            self.assertEqual(target.read_text(),saved.read_text())

    def test_current_hand_calibration_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            saved=Path(folder)/'saved.json';target=Path(folder)/'config.json'
            saved.write_text('old');target.write_text('new')
            launch.prepare_camera_config(saved,target)
            self.assertEqual(target.read_text(),'new')


if __name__ == '__main__': unittest.main()
