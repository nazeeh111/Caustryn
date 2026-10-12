# SPDX-License-Identifier: MIT
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile
from phaseglass import solve
from phaseglass.export import export_zip
from phaseglass.io import decode, encoded, write_new
from phaseglass.resources import resource_root
from phaseglass.server import Handler, StudioServer, analyze, JobCancelled


class DeliveryControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = resource_root()
        cls.measurement = json.loads(
            (cls.root / "examples/measurements/mirror-profiled.json").read_text()
        )
        cls.server = StudioServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def request(self, method, path, body=None, headers=None):
        port = self.server.server_address[1]
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return result

    def test_strict_json_and_no_clobber(self):
        for raw in (
            b'{"x":1,"x":2}',
            b'{"x":NaN}',
            b'"\xff"',
            b"[" * 2000 + b"]" * 2000,
        ):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                decode(raw)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "saved.json"
            write_new(target, b"original")
            with self.assertRaises(FileExistsError):
                write_new(target, b"overwrite")
            self.assertEqual(target.read_bytes(), b"original")

    def test_api_origin_paths_payload_bounds_and_admission(self):
        status, data, headers = self.request("GET", "/api/examples")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(data)), 12)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        for path in ("/../../LICENSE", "/%2e%2e/LICENSE", "/phaseglass/inverse.py"):
            self.assertEqual(self.request("GET", path)[0], 404)
        for headers in ({"Host": "evil.test"}, {"Origin": "https://evil.test"}):
            self.assertEqual(self.request("GET", "/", headers=headers)[0], 403)
        self.assertEqual(
            self.request("POST", "/api/solve", b"{}", {"Content-Type": "text/plain"})[
                0
            ],
            415,
        )
        self.assertEqual(
            self.request(
                "POST",
                "/api/solve",
                b"{}",
                {"Content-Type": "application/json", "Content-Length": "2097153"},
            )[0],
            413,
        )
        truth = dict(self.measurement, position_m=[1, 2, 3])
        status, data, _ = self.request(
            "POST",
            "/api/solve",
            encoded({"measurement": truth}),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 422)
        self.assertIn("truth/pose", json.loads(data)["error"])
        self.server.job_slots.acquire()
        self.server.job_slots.acquire()
        try:
            self.assertEqual(
                self.request(
                    "POST", "/api/solve", b"{}", {"Content-Type": "application/json"}
                )[0],
                429,
            )
        finally:
            self.server.job_slots.release()
            self.server.job_slots.release()

    def test_actual_http_blind_solve(self):
        status, data, _ = self.request(
            "POST",
            "/api/solve",
            encoded({"measurement": self.measurement}),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        result = json.loads(data)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["status"], "multiple-compatible-modes")

    def test_portable_recomputes_then_reruns_without_generator_truth(self):
        data = export_zip(
            {
                "measurement": self.measurement,
                "result": {"status": "FAKE"},
                "truth": {"position_m": [99, 99, 99]},
            }
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                archive.extractall(root)
            manifest = json.loads((root / "manifest.json").read_text())
            self.assertEqual(
                manifest["result_provenance"], "recomputed-from-measurement-at-export"
            )
            saved = json.loads((root / "result.json").read_text())
            self.assertEqual(saved["candidate_count"], 2)
            for name, digest in json.loads(
                (root / "SHA256SUMS.json").read_text()
            ).items():
                self.assertEqual(
                    hashlib.sha256((root / name).read_bytes()).hexdigest(), digest
                )
            # Truth and the generator are unavailable in this separate rerun.
            (root / "truth.json").unlink()
            (root / "phaseglass/simulation.py").write_text(
                'def simulate(*args):\n    raise AssertionError("generator cannot run")\n'
            )
            result_path = root / "rerun.json"
            command = [
                sys.executable,
                str(root / "rerun.py"),
                "--output",
                str(result_path),
            ]
            run = subprocess.run(
                command, cwd=root.parent, capture_output=True, timeout=30
            )
            self.assertEqual(run.returncode, 0, run.stderr.decode())
            result = json.loads(result_path.read_text())
            self.assertEqual(result["measurement_sha256"], saved["measurement_sha256"])
            self.assertEqual(result["status"], saved["status"])
            self.assertEqual(result["candidate_count"], 2)

    def test_worker_deadline_and_actual_disconnect_reap_child(self):
        real_popen = subprocess.Popen
        children = []

        def sleeper(*args, **kwargs):
            child = real_popen(
                [sys.executable, "-c", "import time; time.sleep(30)"], **kwargs
            )
            children.append(child)
            return child

        with (
            patch("phaseglass.server.subprocess.Popen", side_effect=sleeper),
            patch("phaseglass.server.WORKER_SECONDS", 0.1),
        ):
            with self.assertRaisesRegex(ValueError, "25-second"):
                analyze("solve", {"measurement": self.measurement})
        self.assertIsNotNone(children[-1].returncode)
        left, right = socket.socketpair()
        right.close()
        try:
            with patch("phaseglass.server.subprocess.Popen", side_effect=sleeper):
                with self.assertRaises(JobCancelled):
                    analyze("solve", {"measurement": self.measurement}, left)
            self.assertIsNotNone(children[-1].returncode)
        finally:
            left.close()
