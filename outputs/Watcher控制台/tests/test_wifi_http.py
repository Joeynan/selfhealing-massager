import sys, threading, unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'camera'))
from wifi_camera import WiFiFrameReader,MAX_JPEG
from test_wifi_camera import JPEG,headers

class WiFiHTTPTests(unittest.TestCase):
    def setUp(self):
        self.payload=JPEG;self.fields=headers();self.requests=[]
        parent=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                parent.requests.append(self.path)
                self.send_response(200)
                for k,v in parent.fields.items():self.send_header(k,v)
                self.end_headers();self.wfile.write(parent.payload)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.reader=WiFiFrameReader('http://127.0.0.1:'+str(self.server.server_port)+'/frame','watcher-test')
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def test_real_http_reads_metadata_and_drops_cached_frame(self):
        first=self.reader.fetch()
        self.assertEqual(first.jpeg,JPEG);self.assertEqual(first.width,416)
        self.assertIsNone(self.reader.fetch());self.assertEqual(self.requests,['/frame','/frame'])
    def test_truncated_http_body_is_rejected(self):
        self.payload=JPEG[:-2]
        with self.assertRaises((ValueError,OSError)):self.reader.fetch()
    def test_oversized_content_length_rejected_before_body_use(self):
        self.fields['Content-Length']=str(MAX_JPEG+1)
        with self.assertRaises(ValueError):self.reader.fetch()
    def test_wrong_camera_identity_is_rejected_on_network(self):
        self.fields['X-Watcher-Id']='watcher-other'
        with self.assertRaises(ValueError):self.reader.fetch()
    def test_only_supported_snapshot_url_is_accepted(self):
        for url in ['https://host/frame','http://user:pass@host/frame','http://host/screen','http://host/frame?x=1']:
            with self.subTest(url=url),self.assertRaises(ValueError):WiFiFrameReader(url,'watcher-test')

if __name__=='__main__':unittest.main()
