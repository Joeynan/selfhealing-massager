import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'camera'))
from runtime_state import FramePipeline

class WiFiRuntimeTests(unittest.TestCase):
    def test_published_result_keeps_proof_of_its_image_not_newer_capture(self):
        p=FramePipeline()
        self.assertTrue(hasattr(p,'capture_wifi'),'Wi-Fi capture pipeline is missing')
        p.capture_wifi(b'jpeg-a',1000,'boot-a',3)
        frame=p.take_latest()
        p.capture_wifi(b'jpeg-b',1100,'boot-a',4)
        self.assertTrue(p.complete(frame,[],1150,416,416))
        s=p.snapshot(1150)
        self.assertEqual(s['camera_session_id'],'boot-a')
        self.assertEqual(s['camera_frame_id'],3)
        self.assertEqual(s['transport'],'wifi')

    def test_reboot_invalidates_pending_inference_and_resets_action_history(self):
        p=FramePipeline()
        self.assertTrue(hasattr(p,'capture_wifi'),'Wi-Fi capture pipeline is missing')
        p.capture_wifi(b'old',1000,'old',20);old=p.take_latest()
        p.capture_wifi(b'new',1200,'new',1)
        self.assertFalse(p.complete(old,[],1250,416,416))
        new=p.take_latest()
        self.assertIsNotNone(new)
        self.assertTrue(p.complete(new,[],1260,416,416))
        self.assertEqual(p.snapshot(1260)['camera_session_id'],'new')

    def test_repeated_remote_frame_does_not_accumulate_static_confirmations(self):
        p=FramePipeline()
        self.assertTrue(hasattr(p,'capture_wifi'),'Wi-Fi capture pipeline is missing')
        p.capture_wifi(b'first',1000,'boot',7)
        p.capture_wifi(b'repeated',1200,'boot',7)
        self.assertEqual(p.sequence,1)

if __name__=='__main__':unittest.main()
