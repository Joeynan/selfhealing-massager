"""Load model content safely from Chinese and space paths; no camera opened."""
import hashlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'camera'))
from landmark_server import App

class ModelPathTests(unittest.TestCase):
    def test_native_model_loader_receives_bytes_from_unicode_space_path(self):
        base = Mock(return_value='base-options')
        base.Delegate = SimpleNamespace(CPU='CPU')
        create = Mock(return_value='loaded-model')
        options = Mock(return_value='hand-options')
        mp = SimpleNamespace(tasks=SimpleNamespace(BaseOptions=base, vision=SimpleNamespace(
            HandLandmarkerOptions=options, RunningMode=SimpleNamespace(LIVE_STREAM='live'),
            HandLandmarker=SimpleNamespace(create_from_options=create))))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'中文 model'/ 'hand.task'
            path.parent.mkdir(); path.write_bytes(b'verified-model-content')
            app = App(Path(folder)/'state')
            with patch.dict(sys.modules, {'mediapipe': mp}):
                app.initialize_model(path)
        self.assertNotIn('model_asset_path', base.call_args.kwargs)
        self.assertEqual(base.call_args.kwargs.get('model_asset_buffer'), b'verified-model-content')
        self.assertEqual(base.call_args.kwargs['delegate'], 'CPU')
        self.assertEqual(app.model_sha256, hashlib.sha256(b'verified-model-content').hexdigest())
        self.assertEqual(app.model, 'loaded-model')
        self.assertEqual(options.call_args.kwargs['num_hands'], 2)
        self.assertEqual(options.call_args.kwargs['running_mode'], 'live')
        self.assertEqual(options.call_args.kwargs['result_callback'], app.on_result)
        create.assert_called_once_with('hand-options')

if __name__ == '__main__': unittest.main()
