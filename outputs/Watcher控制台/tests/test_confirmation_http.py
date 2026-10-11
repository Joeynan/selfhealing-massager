import json
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'camera'))
from landmark_server import App, make_server


class ConfirmationHTTPTests(unittest.TestCase):
    def test_confirmation_reset_endpoint_returns_barrier_and_clears_old_callback_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            app=App(directory)
            app.pipeline.capture(b'old',100)
            old=app.pipeline.take_latest()
            app.input_images[100]=(old,None)
            server=make_server(app,0);worker=Thread(target=server.serve_forever,daemon=True);worker.start()
            try:
                request=Request('http://127.0.0.1:'+str(server.server_address[1])+'/reset_confirmation',data=b'{}',headers={'Content-Type':'application/json'})
                try:
                    with urlopen(request,timeout=2) as response:status=response.status;result=json.load(response)
                except HTTPError as error:
                    status=error.code;result=json.load(error)
                self.assertEqual(status,200,'confirmation reset endpoint is missing')
                self.assertTrue(result.get('ok'))
                self.assertEqual(result.get('confirmation_generation'),1)
                self.assertGreater(result.get('confirmation_reset_monotonic_ms',0),100)
                self.assertIsNone(app.pipeline.latest)
                result=type('Result',(),{'hand_landmarks':[]})()
                app.on_result(result,None,100)
                self.assertNotIn(100,app.input_images)
                self.assertIsNone(app.pipeline.published)
                self.assertEqual(app.pipeline.inference_error,'')
            finally:
                server.shutdown();server.server_close();worker.join(timeout=2)

if __name__=='__main__':unittest.main()
