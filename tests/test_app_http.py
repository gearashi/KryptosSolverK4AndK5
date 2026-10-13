import json
from pathlib import Path
import shutil
import threading
import unittest
import urllib.error
import urllib.request
import uuid

from kryptos.app import make_server, strict_json, browser_safe_integers


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.folder=Path("research")/(".http-test-"+uuid.uuid4().hex)
        self.server=make_server(self.folder,0,probe=False)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url=f"http://127.0.0.1:{self.server.server_port}"
        self.client=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.manager.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        assert self.folder.resolve().is_relative_to(Path("research").resolve()) and self.folder.name.startswith(".http-test-")
        shutil.rmtree(self.folder)

    def call(self,path,data=None,headers=None):
        request=urllib.request.Request(self.url+path,data=data,headers=headers or {})
        try:
            response=self.client.open(request,timeout=5)
        except urllib.error.HTTPError as error:
            response=error
        with response:
            raw=response.read()
            return response.status,json.loads(raw) if response.headers.get_content_type()=="application/json" else raw,response.headers

    def test_idle_page_presets_and_local_security(self):
        status,info,headers=self.call("/api/info")
        self.assertEqual(status,200)
        self.assertEqual(len(info["k4"]["ciphertext"]),97)
        self.assertGreaterEqual(len(info["presets"]),3)
        self.assertIsNone(self.call("/api/status")[1]["run"])
        self.assertIn("frame-ancestors 'none'",headers["Content-Security-Policy"])
        self.assertEqual(self.call("/",headers={"Host":"evil.example"})[0],403)
        self.assertEqual(self.call("/api/start",data=b"{}",headers={"Content-Type":"application/json"})[0],403)
        auth={"Content-Type":"application/json","X-Kryptos-Token":info["control_token"]}
        self.assertEqual(self.call("/api/start",data=b"{}",headers={**auth,"Origin":"https://evil.example"})[0],403)
        self.assertEqual(self.call("/api/start",data=b'{"kind":"exact","kind":"exact"}',headers=auth)[0],400)
        for value in (b'{"number":1e309}',b'{"number":NaN}',b'{"number":-Infinity}'):
            self.assertEqual(self.call("/api/start",data=value,headers=auth)[0],400)
        self.assertIsNone(self.call("/api/status")[1]["run"])
        self.assertEqual(self.call("/static/mark.svg")[0],200)
        self.assertEqual(self.call("/../README.md")[0],404)

    def test_exact_large_counts_survive_browser_json(self):
        original={"count":2**70+1,"negative":-(2**80+1),"boolean":True,"small":97}
        encoded=json.loads(json.dumps(browser_safe_integers(original)))
        self.assertEqual(int(encoded["count"]["value"],16),original["count"])
        self.assertEqual(int(encoded["negative"]["value"],16),original["negative"])
        self.assertIs(encoded["boolean"],True)
        self.assertEqual(encoded["small"],97)

    def test_control_and_export_flow(self):
        info=self.call("/api/info")[1]
        auth={"Content-Type":"application/json","X-Kryptos-Token":info["control_token"]}
        data={k:v for k,v in next(p for p in info["presets"] if p["id"]=="joint-ragged").items() if k in {"kind","command","request"}}
        status,value,_=self.call("/api/start",json.dumps(data).encode(),auth)
        self.assertEqual(status,200,value)
        key=value["run"]["id"]
        self.server.manager.thread.join(timeout=10)
        result=self.call("/api/runs/"+key)[1]["run"]
        self.assertEqual(result["state"],"completed",result.get("error"))
        exported=self.call("/api/export?run_id="+key)
        self.assertEqual(exported[1]["id"],key)
        self.assertIn("attachment",exported[2]["Content-Disposition"])
        self.assertTrue(exported[1]["candidates"][0]["evidence"]["literal_reencryption_matches"])


if __name__=="__main__":
    unittest.main()
