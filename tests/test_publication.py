# SPDX-License-Identifier: MIT
"""Controls for create-only complete-file publication."""
import concurrent.futures
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from phaseglass.io import write_new


class PublicationTests(unittest.TestCase):
    def test_real_short_write_has_no_final_and_can_retry(self):
        program = '''
import resource, signal, sys
from phaseglass.io import write_new
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE, (4096, 4096))
try:
    write_new(sys.argv[1], b"Z" * 100000)
except OSError as error:
    assert error.errno == __import__("errno").EFBIG, error.errno
else:
    raise AssertionError("expected file-size error")
'''
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "artifact.zip"
            result = subprocess.run([sys.executable, "-c", program, str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(folder).iterdir()), [])
            write_new(target, b"complete retry")
            self.assertEqual(target.read_bytes(), b"complete retry")

    def test_existing_file_and_dangling_symlink_never_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "existing"
            original.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                write_new(original, b"replacement")
            self.assertEqual(original.read_bytes(), b"existing")
            link = root / "link"
            link.symlink_to(root / "missing")
            with self.assertRaises(FileExistsError):
                write_new(link, b"replacement")
            self.assertTrue(link.is_symlink())
            self.assertFalse((root / "missing").exists())
            self.assertFalse(list(root.glob(".phaseglass-*")))

    def test_race_and_interruption_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "result"
            link = os.link
            def race(source, destination):
                target.write_bytes(b"other owner")
                link(source, destination)
            with patch("phaseglass.io.os.link", side_effect=race):
                with self.assertRaises(FileExistsError):
                    write_new(target, b"ours")
            self.assertEqual(target.read_bytes(), b"other owner")
            pending = root / "interrupt"
            with patch("phaseglass.io.os.link", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    write_new(pending, b"ours")
            self.assertFalse(pending.exists())
            self.assertFalse(list(root.glob(".phaseglass-*")))

    def test_concurrent_writers_leave_one_complete_winner(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "artifact"
            barrier = threading.Barrier(2)
            link = os.link
            def synchronized(source, destination):
                barrier.wait(timeout=5)
                link(source, destination)
            payloads = [b"A" * 200000, b"B" * 200000]
            def run(payload):
                try:
                    write_new(target, payload)
                    return "success"
                except FileExistsError:
                    return "exists"
            with patch("phaseglass.io.os.link", side_effect=synchronized):
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(run, payloads))
            self.assertCountEqual(results, ["success", "exists"])
            self.assertIn(target.read_bytes(), payloads)
            self.assertFalse(list(Path(folder).glob(".phaseglass-*")))

    def test_stage_failure_after_publication_keeps_complete_result(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "artifact"
            with patch("phaseglass.io.os.unlink", side_effect=OSError(errno.EACCES, "denied")):
                with self.assertRaises(OSError):
                    write_new(target, b"complete")
            self.assertEqual(target.read_bytes(), b"complete")
            self.assertEqual(len(list(Path(folder).glob(".phaseglass-*"))), 1)

    def test_replaced_stage_is_not_deleted_during_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "artifact"
            displaced = root / "displaced-stage"
            replaced = []
            def replace_then_interrupt(source, destination):
                source = Path(source)
                source.rename(displaced)
                source.write_bytes(b"another owner")
                replaced.append(source)
                raise KeyboardInterrupt
            with patch("phaseglass.io.os.link", side_effect=replace_then_interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    write_new(target, b"ours")
            self.assertFalse(target.exists())
            self.assertEqual(displaced.read_bytes(), b"ours")
            self.assertEqual(replaced[0].read_bytes(), b"another owner")

    def test_real_sigint_at_first_fstat_closes_descriptor_and_removes_stage(self):
        import signal
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "artifact"
            actual_fstat = os.fstat
            seen = []
            def interrupt_once(fd):
                seen.append(fd)
                if len(seen) == 1:
                    signal.raise_signal(signal.SIGINT)
                return actual_fstat(fd)
            with patch("phaseglass.io.os.fstat", side_effect=interrupt_once):
                with self.assertRaises(KeyboardInterrupt):
                    write_new(target, b"complete")
            self.assertEqual(len(seen), 2)
            with self.assertRaises(OSError) as error:
                actual_fstat(seen[0])
            self.assertEqual(error.exception.errno, errno.EBADF)
            self.assertFalse(target.exists())
            self.assertEqual(list(root.iterdir()), [])
            write_new(target, b"retry")
            self.assertEqual(target.read_bytes(), b"retry")

    def test_unrecoverable_stat_keeps_unverifiable_stage_but_closes_descriptor(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "artifact"
            actual_fstat = os.fstat
            seen = []
            def fail(fd):
                seen.append(fd)
                raise OSError(errno.EIO, "injected stat failure")
            with patch("phaseglass.io.os.fstat", side_effect=fail):
                with self.assertRaises(OSError):
                    write_new(target, b"complete")
            self.assertEqual(len(seen), 2)
            with self.assertRaises(OSError) as error:
                actual_fstat(seen[0])
            self.assertEqual(error.exception.errno, errno.EBADF)
            self.assertFalse(target.exists())
            self.assertEqual(len(list(root.glob(".phaseglass-*"))), 1)
