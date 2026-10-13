# SPDX-License-Identifier: MIT
import copy
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from phaseglass import coherent_export
from phaseglass.coherent import evaluate_sweep


FIXTURES = Path(__file__).resolve().parents[1] / "examples" / "coherent"


def packet(name, kind):
    return json.loads((FIXTURES / (name + "." + kind + ".json")).read_text())


def unzip(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def locked_environment():
    try:
        return (sys.implementation.name == "cpython" and sys.version_info >= (3, 12)
                and importlib.metadata.version("numpy") == "2.3.5"
                and importlib.metadata.version("scipy") == "1.18.1")
    except importlib.metadata.PackageNotFoundError:
        return False


def refresh_checksums(files):
    files["SHA256SUMS.json"] = json.dumps({
        name: hashlib.sha256(data).hexdigest() for name, data in files.items()
        if name != "SHA256SUMS.json"}, sort_keys=True).encode()


class CoherentExportContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = {"training": packet("free-response", "training"),
                       "validation": packet("free-response", "validation"),
                       "context": {"truth": packet("free-response", "truth")}}
        cls.files = unzip(coherent_export.export_sweep(cls.request))
        cls.result = json.loads(cls.files["result.json"])

    def test_exact_packets_actual_source_notices_hashes_and_lock(self):
        files = self.files
        self.assertLess(sum(map(len, files.values())), 4 * 1024 * 1024)
        for name in files:
            self.assertFalse(Path(name).is_absolute())
            self.assertNotIn("..", Path(name).parts)
            self.assertNotIn("\\", name)
            self.assertNotIn(":", name)
        for key in ("training", "validation", "context"):
            self.assertEqual(json.loads(files[key + ".json"]), self.request[key])
        self.assertEqual(files["requirements.lock"], b"numpy==2.3.5\nscipy==1.18.1\n")
        self.assertIn(b"Permission is hereby granted", files["LICENSE"])
        self.assertIn(b"NumPy", files["THIRD_PARTY_NOTICES.md"])
        for source in Path(coherent_export.__file__).parent.glob("*.py"):
            self.assertEqual(files["phaseglass/" + source.name], source.read_bytes())
        manifest = json.loads(files["manifest.json"])
        for key in ("training", "validation", "context", "result"):
            self.assertEqual(manifest["canonical_sha256"][key],
                             coherent_export.canonical_sha256(json.loads(files[key+".json"])))
        self.assertEqual(manifest["canonical_sha256"]["training"], self.result["fit"]["training_sha256"])
        self.assertEqual(manifest["optional_context"]["status"], "supplied-unverified-never-inference-input")
        checksums = json.loads(files["SHA256SUMS.json"])
        self.assertEqual(set(checksums), set(files) - {"SHA256SUMS.json"})
        for name, digest in checksums.items():
            self.assertEqual(hashlib.sha256(files[name]).hexdigest(), digest)

    def test_forged_client_results_and_arbitrary_context_never_enter_inference(self):
        request = copy.deepcopy(self.request)
        request["result"] = {"fit": {"status": "FORGED", "candidates": [{"position_m": [999,999,999]}]}}
        request["context"] = {"truth": {"point_m": [999,999,999]},
                              "force_mode": "hide-other-branches", "script": "DO_NOT_RUN"}
        with patch.object(coherent_export, "evaluate_sweep", wraps=evaluate_sweep) as actual:
            files = unzip(coherent_export.export_sweep(request))
        self.assertEqual(actual.call_count, 1)
        self.assertEqual(actual.call_args.args, (request["training"], request["validation"]))
        self.assertEqual(actual.call_args.kwargs, {})
        result = json.loads(files["result.json"])
        self.assertNotIn("FORGED", files["result.json"].decode())
        self.assertEqual(result["fit"]["candidates"], self.result["fit"]["candidates"])
        self.assertEqual(json.loads(files["context.json"]), request["context"])
        self.assertFalse(result["validation"]["gain_refitted"])
        self.assertFalse(result["validation"]["location_refitted"])
        self.assertFalse(result["validation"]["mode_selected_using_held_iq"])

    def test_changed_held_iq_is_new_evidence_without_training_feedback(self):
        request = copy.deepcopy(self.request)
        request["validation"]["iq"]["real"][0][0][0] += .05
        changed = unzip(coherent_export.export_sweep(request))
        result = json.loads(changed["result.json"])
        old_manifest, new_manifest = (json.loads(x["manifest.json"]) for x in (self.files, changed))
        self.assertNotEqual(old_manifest["canonical_sha256"]["validation"], new_manifest["canonical_sha256"]["validation"])
        self.assertEqual(result["fit"]["candidates"], self.result["fit"]["candidates"])
        self.assertNotEqual(result["validation"]["candidates"][0]["relative_iq_residual"],
                            self.result["validation"]["candidates"][0]["relative_iq_residual"])

    def test_stale_training_digest_is_rejected(self):
        request = copy.deepcopy(self.request)
        request["training"]["name"] += "-edited"
        with self.assertRaisesRegex(ValueError, "different canonical training"):
            coherent_export.export_sweep(request)

    def test_browser_integral_number_roundtrip_preserves_core_and_bundle_identity(self):
        def browser_numbers(value):
            if type(value) is float and value.is_integer():
                return int(value)
            if type(value) is list:
                return [browser_numbers(item) for item in value]
            if type(value) is dict:
                return {key: browser_numbers(item) for key, item in value.items()}
            return value
        request = browser_numbers(self.request)
        files = unzip(coherent_export.export_sweep(request))
        manifest = json.loads(files["manifest.json"])
        result = json.loads(files["result.json"])
        self.assertEqual(manifest["canonical_sha256"]["training"], self.result["fit"]["training_sha256"])
        self.assertEqual(result["fit"]["training_sha256"], manifest["canonical_sha256"]["training"])
        self.assertEqual(result["fit"]["candidates"], self.result["fit"]["candidates"])
        self.assertEqual(json.loads(files["training.json"]), request["training"])

    def test_embedded_runner_hash_normalizes_integral_floats_and_negative_zero(self):
        # Execute our own actual runner definitions without invoking its main.
        namespace = {"__name__": "phaseglass_export_hash_control"}
        exec(coherent_export.RUNNER, namespace)
        values = [{"nested": [1.0, -0.0, 5.5], "marker": False},
                  {"nested": [1, 0, 5.5], "marker": False}]
        hashes = [coherent_export.canonical_sha256(value) for value in values]
        self.assertEqual(hashes[0], hashes[1])
        for value in values:
            self.assertEqual(namespace["canonical"](value), hashes[0])
        self.assertNotEqual(hashes[0], coherent_export.canonical_sha256({"nested": [1,0,5.5], "marker": 0}))

    def test_fit_only_export_has_no_held_or_context_input(self):
        files = unzip(coherent_export.export_sweep({"training": self.request["training"]}))
        result = json.loads(files["result.json"])
        self.assertIn("candidates", result)
        self.assertNotIn("validation.json", files)
        self.assertNotIn("context.json", files)
        self.assertEqual(json.loads(files["manifest.json"])["solver_inputs"], ["training.json"])

    def test_all_retained_mirror_branches_are_exported_and_predicted(self):
        files = unzip(coherent_export.export_sweep({"training": packet("mirror", "training"),
                                                   "validation": packet("mirror", "validation")}))
        result = json.loads(files["result.json"])
        self.assertGreaterEqual(result["fit"]["candidate_count"], 2)
        self.assertEqual(len(result["fit"]["candidates"]), len(result["validation"]["candidates"]))
        self.assertFalse(result["validation"]["mode_selected_using_held_iq"])
        self.assertEqual([x["position_m"] for x in result["fit"]["candidates"]],
                         [x["position_m"] for x in result["validation"]["candidates"]])

    def test_request_shape_finiteness_nesting_and_2mib_bound_before_fit(self):
        malformed = [{}, {"training": self.request["training"], "truth": {}},
                     {"training": self.request["training"], "context": []},
                     {"training": self.request["training"], "validation": None},
                     {"training": self.request["training"], "result": float("nan")},
                     {"training": self.request["training"], "result": "x" * (2*1024*1024)}]
        nested = 0
        for _ in range(40):
            nested = [nested]
        malformed.append({"training": self.request["training"], "context": {"nested": nested}})
        with patch.object(coherent_export, "evaluate_sweep") as evaluate, patch.object(coherent_export, "solve_sweep") as solve:
            for request in malformed:
                with self.subTest(request_kind=list(request)):
                    with self.assertRaises(ValueError):
                        coherent_export.export_sweep(request)
            evaluate.assert_not_called()
            solve.assert_not_called()

    def test_portable_4mib_content_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "LICENSE").write_bytes(b"x" * (4*1024*1024))
            (root / "THIRD_PARTY_NOTICES.md").write_text("test oversized resource")
            with patch.object(coherent_export, "resource_root", return_value=root):
                with self.assertRaisesRegex(ValueError, "contents exceed 4 MiB"):
                    coherent_export.export_sweep({"training": self.request["training"]})

    def _rerun(self, files, existing=False):
        with tempfile.TemporaryDirectory(prefix="phaseglass-coherent-export-") as directory:
            root = Path(directory)
            bundle, other = root / "bundle", root / "outside"
            other.mkdir()
            for name, content in files.items():
                target = bundle / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            output = other / "NEW.json"
            if existing:
                output.write_bytes(b"preserve these exact bytes")
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            result = subprocess.run([sys.executable, str(bundle / "rerun.py"), "--output", str(output)],
                                    cwd=other, env=env, capture_output=True, text=True, timeout=35)
            return result, output.read_bytes() if output.exists() else None

    @unittest.skipUnless(locked_environment(), "Replay lock control requires CPython>=3.12, NumPy2.3.5, SciPy1.18.1")
    def test_outside_directory_blind_replay_without_truth_or_generator_body(self):
        # Deliberately change a COPY, refreshing its manifest, to test dependencies.
        # Deleting files under the original manifest must fail, tested separately.
        files = dict(self.files)
        files.pop("context.json")
        files["phaseglass/simulation.py"] = b'def simulate(*args, **kwargs):\n    raise AssertionError("Original generator body removed; blind replay must not call it")\n'
        manifest = json.loads(files["manifest.json"])
        del manifest["canonical_sha256"]["context"]
        manifest["optional_context"]["present"] = False
        manifest["independent_control"] = "Original generator body and all truth/context removed; import shim raises if called"
        files["manifest.json"] = json.dumps(manifest).encode()
        refresh_checksums(files)
        process, output = self._rerun(files)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(output)
        self.assertEqual(result["fit"]["training_sha256"], self.result["fit"]["training_sha256"])
        self.assertEqual(result["fit"]["candidates"], self.result["fit"]["candidates"])
        self.assertEqual(result["validation"]["candidates"], self.result["validation"]["candidates"])
        self.assertFalse(result["validation"]["gain_refitted"])

    @unittest.skipUnless(locked_environment(), "Replay lock control requires CPython>=3.12, NumPy2.3.5, SciPy1.18.1")
    def test_checksum_changes_and_source_deletion_are_refused_before_fit(self):
        for name in ("training.json", "phaseglass/coherent.py"):
            files = dict(self.files)
            files[name] += b"\nchanged"
            process, output = self._rerun(files)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("Checksum mismatch", process.stderr)
            self.assertIsNone(output)
        files = dict(self.files)
        del files["phaseglass/simulation.py"]
        process, output = self._rerun(files)
        self.assertNotEqual(process.returncode, 0)
        self.assertIsNone(output)

    @unittest.skipUnless(locked_environment(), "Replay lock control requires CPython>=3.12, NumPy2.3.5, SciPy1.18.1")
    def test_fit_only_outside_directory_replay(self):
        files = unzip(coherent_export.export_sweep({"training": self.request["training"]}))
        process, output = self._rerun(files)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(output)
        self.assertEqual(result["training_sha256"], self.result["fit"]["training_sha256"])
        self.assertEqual(result["candidates"], self.result["fit"]["candidates"])

    @unittest.skipUnless(locked_environment(), "Replay lock control requires CPython>=3.12, NumPy2.3.5, SciPy1.18.1")
    def test_existing_output_is_not_clobbered(self):
        process, output = self._rerun(self.files, existing=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("Output already exists", process.stderr)
        self.assertEqual(output, b"preserve these exact bytes")


if __name__ == "__main__":
    unittest.main()
