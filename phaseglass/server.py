# SPDX-License-Identifier: MIT
"""Loopback studio with bounded fixed-operation workers and disconnect cancellation."""

import base64
import mimetypes
import os
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
from .io import MAX_INPUT, decode, encoded
from .resources import resource_root

OPERATIONS = {
    "/api/" + name: name for name in ("simulate", "solve", "intervention", "export")
}
MAX_OUTPUT = 8 * 1024 * 1024
WORKER_SECONDS = 25


class JobCancelled(ValueError):
    pass


def disconnected(connection):
    if connection is None:
        return False
    readable, _, _ = select.select([connection], [], [], 0)
    if not readable:
        return False
    try:
        return connection.recv(1, socket.MSG_PEEK) == b""
    except (OSError, ValueError):
        return True


def analyze(action, payload, connection=None):
    request = encoded({"action": action, "payload": payload})
    if len(request) > MAX_INPUT:
        raise ValueError("Request exceeds 2 MiB")
    env = dict(os.environ)
    # Prevent numerical libraries from creating oversized thread pools per job.
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as sink:
        source.write(request)
        source.seek(0)
        # A portable runner may be invoked outside its archive directory. Pass
        # our own source location, never a request-supplied path, to its child.
        bootstrap = "import sys;sys.path.insert(0,sys.argv[1]);from phaseglass.worker import main;raise SystemExit(main())"
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                bootstrap,
                str(Path(__file__).resolve().parent.parent),
            ],
            stdin=source,
            stdout=sink,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        deadline = time.monotonic() + WORKER_SECONDS
        try:
            while process.poll() is None:
                if disconnected(connection):
                    raise JobCancelled("Client disconnected; worker stopped")
                if time.monotonic() >= deadline:
                    raise ValueError("Operation stopped at the 25-second limit")
                if os.fstat(sink.fileno()).st_size > MAX_OUTPUT:
                    raise ValueError("Worker output exceeds 8 MiB")
                time.sleep(0.025)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
        sink.seek(0)
        raw = sink.read(MAX_OUTPUT + 1)
    if len(raw) > MAX_OUTPUT:
        raise ValueError("Worker output exceeds 8 MiB")
    try:
        response = __import__("json").loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("Worker did not return a valid response") from None
    if type(response) is not dict or not response.get("ok") or process.returncode != 0:
        raise ValueError(
            response.get("error", "Worker failed")
            if type(response) is dict
            else "Worker failed"
        )
    return response["result"]


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, *args, **kwargs):
        self.connection_slots = threading.BoundedSemaphore(16)
        self.job_slots = threading.BoundedSemaphore(2)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.connection_slots.acquire(False):
            try:
                request.settimeout(0.25)
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.connection_slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "Phaseglass/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass

    def send(self, status, value, kind="application/json", download=False):
        body = value if isinstance(value, bytes) else encoded(value)
        self.send_response(status)
        for key, item in {
            "Content-Type": kind,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        }.items():
            self.send_header(key, item)
        if download:
            self.send_header(
                "Content-Disposition",
                'attachment; filename="phaseglass-experiment.zip"',
            )
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        port = self.server.server_address[1]
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"} and origin in (
            None,
            f"http://{host}",
        )

    def do_GET(self):
        if not self.allowed():
            self.send(403, {"error": "Host or origin is not allowed"})
            return
        path = unquote(urlsplit(self.path).path)
        root = resource_root()
        if path == "/api/examples":
            from .io import read_json

            self.send(200, read_json(root / "examples" / "studio.json"))
            return
        name = "index.html" if path == "/" else path.lstrip("/")
        # Only ship studio assets, never generic local-file access.
        target = (root / "studio" / name).resolve()
        if (
            ".." in path.split("/")
            or not target.is_relative_to((root / "studio").resolve())
            or not target.is_file()
        ):
            self.send(404, {"error": "Not found"})
            return
        kind = (
            "text/javascript"
            if target.suffix == ".js"
            else mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        )
        self.send(200, target.read_bytes(), kind)

    def do_POST(self):
        if not self.server.job_slots.acquire(False):
            self.close_connection = True
            self.send(429, {"error": "Two operations are already processing"})
            return
        try:
            if not self.allowed():
                self.send(403, {"error": "Host or origin is not allowed"})
                return
            action = OPERATIONS.get(urlsplit(self.path).path)
            if action is None:
                self.send(404, {"error": "Not found"})
                return
            if self.headers.get("Transfer-Encoding"):
                self.send(400, {"error": "Transfer-Encoding is unsupported"})
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_INPUT - 100:
                self.send(413, {"error": "Request exceeds 2 MiB"})
                return
            if (
                self.headers.get("Content-Type", "").split(";")[0].strip()
                != "application/json"
            ):
                self.send(415, {"error": "JSON content type required"})
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Incomplete request")
            result = analyze(action, decode(raw), self.connection)
            if action == "export":
                self.send(
                    200,
                    base64.b64decode(result["zip_base64"], validate=True),
                    "application/zip",
                    True,
                )
            else:
                self.send(200, result)
        except JobCancelled:
            pass
        except (ValueError, TypeError, KeyError, TimeoutError) as exc:
            self.send(422, {"error": str(exc)[:500]})
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.server.job_slots.release()


def serve(port=6365):
    with StudioServer(("127.0.0.1", port), Handler) as server:
        print(
            f"Phaseglass Studio: http://127.0.0.1:{server.server_address[1]}/",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
