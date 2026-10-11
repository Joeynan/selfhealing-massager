import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'camera'))
try:
    from wifi_camera import WiFiFrameReader
except ImportError:
    WiFiFrameReader = None

JPEG = b'\xff\xd8test-jpeg\xff\xd9'
def headers(**changes):
    h = {'Content-Type':'image/jpeg','Content-Length':str(len(JPEG)),
         'X-Watcher-Id':'watcher-test','X-Capture-Session':'boot-1',
         'X-Frame-Id':'7','X-Frame-Age-Ms':'50',
         'X-Frame-Width':'416','X-Frame-Height':'416'}
    h.update(changes)
    return h

class WiFiCameraTests(unittest.TestCase):
    def reader(self):
        self.assertIsNotNone(WiFiFrameReader, 'Wi-Fi frame reader is not implemented')
        return WiFiFrameReader('http://127.0.0.1:8081/frame', 'watcher-test')

    def test_transport_delay_is_charged_without_comparing_device_epochs(self):
        f = self.reader().decode(JPEG, headers(), 1000, 1200)
        self.assertEqual(f.timestamp_ms, 950)
        self.assertEqual(f.session_id, 'boot-1')
        self.assertEqual(f.frame_id, 7)

    def test_duplicate_and_out_of_order_frames_are_not_reprocessed(self):
        r = self.reader();r.decode(JPEG, headers(), 1000, 1050)
        self.assertIsNone(r.decode(JPEG, headers(), 1200, 1250))
        self.assertIsNone(r.decode(JPEG, headers(**{'X-Frame-Id':'6'}), 1200, 1250))

    def test_new_boot_restarts_sequence_but_retired_boot_cannot_return(self):
        r = self.reader();r.decode(JPEG, headers(), 1000, 1050)
        f=r.decode(JPEG,headers(**{'X-Capture-Session':'boot-2','X-Frame-Id':'1'}),1200,1250)
        self.assertEqual(f.frame_id,1)
        self.assertIsNone(r.decode(JPEG,headers(**{'X-Frame-Id':'9'}),1300,1350))

    def test_stale_image_or_slow_transfer_cannot_be_redated(self):
        for age,end in [('800',1050),('50',1750)]:
            with self.subTest(age=age,end=end), self.assertRaises(ValueError):
                self.reader().decode(JPEG,headers(**{'X-Frame-Age-Ms':age}),1000,end)

    def test_wrong_identity_bad_jpeg_and_incomplete_body_are_rejected(self):
        for body,h in [(JPEG,headers(**{'X-Watcher-Id':'other'})),(JPEG[:-1],headers()),
                       (b'bad!image!!',headers(**{'Content-Length':'11'})),
                       (JPEG,headers(**{'Content-Type':'application/json'})),
                       (JPEG,headers(**{'X-Frame-Id':'0'})),
                       (JPEG,headers(**{'X-Frame-Age-Ms':'nan'})),
                       (JPEG,headers(**{'X-Capture-Session':'a\r\nb'}))]:
            with self.subTest(h=h), self.assertRaises(ValueError):
                self.reader().decode(body,h,1000,1050)

    def test_lost_camera_does_not_fall_back_to_usb(self):
        r=self.reader()
        self.assertEqual(r.url,'http://127.0.0.1:8081/frame')
        self.assertFalse(hasattr(r,'serial'))

if __name__=='__main__':unittest.main()
