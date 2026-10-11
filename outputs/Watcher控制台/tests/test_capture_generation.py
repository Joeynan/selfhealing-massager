"""Requests started before a confirmation reset cannot alter its capture state."""
import sys
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'camera'))
from landmark_server import App
from runtime_state import FramePipeline


class CaptureGenerationTests(unittest.TestCase):
    def run_request(self, pipeline, during_fetch=None, frame=None, error=None):
        # Exercise the real worker without a camera, network request or model.
        app = App.__new__(App)
        app.pipeline = pipeline
        app.stopping = Event()

        class Reader:
            def fetch(self):
                if during_fetch:
                    during_fetch()
                app.stopping.set()
                if error is not None:
                    raise RuntimeError(error)
                return frame

        app.wifi_reader = Reader()
        app.wifi_camera_worker()

    @staticmethod
    def image(timestamp=1200, session='boot-a', frame_id=2):
        return SimpleNamespace(jpeg=b'jpeg', timestamp_ms=timestamp,
                               session_id=session, frame_id=frame_id, transfer_ms=20)

    def test_reset_clears_old_capture_error_and_keeps_proof_unavailable(self):
        p = FramePipeline()
        p.error('HTTP 503 from previous simulation source')
        p.reset_confirmation(1100)
        s = p.snapshot(1120)
        self.assertEqual(s['error'], '')
        self.assertFalse(s['ready'])
        self.assertIsNone(s['camera_session_id'])
        self.assertIsNone(s['camera_frame_id'])
        self.assertFalse(s['confirmed_this_frame'])

    def test_reset_preserves_real_inference_error(self):
        p = FramePipeline()
        p.error('old HTTP 503')
        p.fail_inference('model decode failed')
        p.reset_confirmation(1100)
        self.assertEqual(p.message, '')
        self.assertEqual(p.snapshot(1120)['error'], 'model decode failed')
        self.assertFalse(p.snapshot(1120)['ready'])

    def test_old_request_failure_after_reset_cannot_publish_new_error(self):
        p = FramePipeline()
        self.run_request(p, during_fetch=lambda: p.reset_confirmation(1100), error='old HTTP 503')
        self.assertEqual(p.snapshot(1120)['error'], '')
        self.assertEqual(p.generation, 1)

    def test_old_request_failure_cannot_replace_current_failure(self):
        p = FramePipeline()

        def newer_failure():
            p.reset_confirmation(1100)
            p.error('current connection failure')

        self.run_request(p, during_fetch=newer_failure, error='old HTTP 503')
        self.assertEqual(p.snapshot(1120)['error'], 'current connection failure')
        self.assertEqual(p.generation, 2)

    def test_current_request_failure_immediately_stops_and_invalidates_callback(self):
        p = FramePipeline()
        p.capture_wifi(b'jpeg', 1000, 'boot-a', 1)
        old = p.take_latest()
        before = p.generation
        self.run_request(p, error='current HTTP 503')
        self.assertIn('current HTTP 503', p.snapshot(1120)['error'])
        self.assertFalse(p.snapshot(1120)['ready'])
        self.assertEqual(p.generation, before + 1)
        self.assertFalse(p.complete(old, [], 1120, 416, 416))

    def test_old_request_success_with_new_timestamp_cannot_cross_reset(self):
        p = FramePipeline()
        self.run_request(p, during_fetch=lambda: p.reset_confirmation(1100), frame=self.image())
        self.assertIsNone(p.latest)
        self.assertIsNone(p.published)
        self.assertEqual(p.sequence, 0)
        self.assertEqual(p.generation, 1)

    def test_old_request_success_cannot_replace_new_camera_session(self):
        p = FramePipeline()

        def newer_capture():
            p.reset_confirmation(1100)
            p.capture_wifi(b'new', 1200, 'boot-new', 1)

        self.run_request(p, during_fetch=newer_capture,
                         frame=self.image(timestamp=1300, session='boot-old', frame_id=20))
        self.assertEqual(p.remote_session, 'boot-new')
        self.assertEqual(p.latest.remote_session_id, 'boot-new')
        self.assertNotIn('boot-new', p.retired_sessions)
        self.assertEqual(p.sequence, 1)

    def test_current_post_reset_request_publishes_only_its_new_proof(self):
        p = FramePipeline()
        p.error('old HTTP 503')
        p.reset_confirmation(1100)
        self.run_request(p, frame=self.image())
        frame = p.take_latest()
        self.assertIsNotNone(frame)
        self.assertTrue(p.complete(frame, [], 1250, 416, 416))
        s = p.snapshot(1250)
        self.assertEqual(s['error'], '')
        self.assertTrue(s['ready'])
        self.assertEqual(s['camera_session_id'], 'boot-a')
        self.assertEqual(s['camera_frame_id'], 2)

    def test_camera_reboot_inside_current_response_is_still_accepted(self):
        p = FramePipeline()
        p.capture_wifi(b'old', 1000, 'old-boot', 20)
        self.run_request(p, frame=self.image(session='new-boot', frame_id=1))
        frame = p.take_latest()
        self.assertIsNotNone(frame)
        self.assertTrue(p.complete(frame, [], 1250, 416, 416))
        self.assertEqual(p.snapshot(1250)['camera_session_id'], 'new-boot')

    def test_callback_started_before_reset_cannot_clear_new_pending(self):
        p = FramePipeline()
        p.capture_wifi(b'old', 1000, 'boot-a', 1)
        old = p.take_latest()
        p.reset_confirmation(1100)
        self.run_request(p, frame=self.image())
        new = p.take_latest()
        self.assertFalse(p.complete(old, [], 1250, 416, 416))
        self.assertEqual(p.pending, new)
        self.assertTrue(p.complete(new, [], 1300, 416, 416))

    def test_post_reset_frame_age_expiry_remains_800ms(self):
        p = FramePipeline()
        p.reset_confirmation(1100)
        self.run_request(p, frame=self.image())
        frame = p.take_latest()
        self.assertFalse(p.complete(frame, [], 2000, 416, 416))
        self.assertFalse(p.snapshot(2000)['ready'])
        self.assertIsNone(p.snapshot(2000)['camera_frame_id'])


if __name__ == '__main__':
    unittest.main()
