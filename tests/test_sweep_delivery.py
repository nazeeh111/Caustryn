# SPDX-License-Identifier: MIT
"""New fixed operations and packaged routes, exercised through real workers."""
import http.client
import json
import threading
import unittest
from phaseglass.io import encoded
from phaseglass.resources import resource_root
from phaseglass.server import Handler, StudioServer, analyze
from phaseglass.worker import execute

class SweepDelivery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples=json.loads((resource_root()/'examples/coherent/index.json').read_text())
        cls.case=next(x for x in cls.examples if x['id']=='free-response')
        cls.server=StudioServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(2)
    def request(self,method,path,body=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=30)
        c.request(method,path,body,{'Content-Type':'application/json'})
        r=c.getresponse();status=r.status;data=r.read();c.close();return status,data
    def test_fixed_routes_and_strict_worker_operations(self):
        status,raw=self.request('GET','/api/sweep-examples')
        self.assertEqual(status,200);self.assertEqual(len(json.loads(raw)),9)
        self.assertEqual(self.request('GET','/sweep.html')[0],200)
        packet={'training':self.case['training'],'validation':self.case['validation']}
        status,raw=self.request('POST','/api/sweep-validate',encoded(packet))
        self.assertEqual(status,200,raw);self.assertEqual(json.loads(raw)['training_poses'],5);self.assertEqual(json.loads(raw)['held_poses'],2)
        for operation in ('sweep-solve','sweep-evaluate','sweep-validate'):
            with self.subTest(operation=operation),self.assertRaises(ValueError):
                execute({'action':operation,'payload':dict(packet,truth=self.case['truth'])})
        stale=dict(self.case['validation'],training_sha256='0'*64)
        self.assertEqual(self.request('POST','/api/sweep-validate',encoded(dict(packet,validation=stale)))[0],422)
    def test_real_worker_fit_and_fixed_held_prediction(self):
        fit=analyze('sweep-solve',{'training':self.case['training']})
        self.assertEqual(fit['status'],'one-found-mode-conditional-coherence')
        result=analyze('sweep-evaluate',{'training':self.case['training'],'validation':self.case['validation']})
        self.assertEqual(fit['training_sha256'],result['fit']['training_sha256']);self.assertEqual(fit['candidates'],result['fit']['candidates'])
        self.assertFalse(result['validation']['gain_refitted']);self.assertFalse(result['validation']['location_refitted']);self.assertFalse(result['validation']['mode_selected_using_held_iq'])
        self.assertLess(result['validation']['candidates'][0]['reduced_residual'],3)
