# SPDX-License-Identifier: MIT
"""Fresh blind coherent calculations with source-bearing, bounded replay ZIPs."""

import hashlib
import io
from pathlib import Path
import zipfile

from . import __version__
from .coherent import evaluate_sweep, solve_sweep, training_hash
from .io import MAX_INPUT, decode, encoded
from .resources import resource_root

MAX_CONTENTS = 4 * 1024 * 1024
LOCK = b"numpy==2.3.5\nscipy==1.18.1\n"


def canonical_sha256(value):
    """Finite JSON identity with integral floats and negative zero normalized."""
    return training_hash(value)


RUNNER = r'''# SPDX-License-Identifier: MIT
"""Verify the frozen bundle and rerun blind training/held prediction from anywhere."""
import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys

def semantic_numbers(value):
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Nonfinite JSON number")
        return int(value) if value.is_integer() else value
    if type(value) is list:
        return [semantic_numbers(item) for item in value]
    if type(value) is dict:
        return {key: semantic_numbers(item) for key, item in value.items()}
    return value

def canonical(value):
    return hashlib.sha256(json.dumps(semantic_numbers(value), sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description="Verify and recompute the included blind coherent experiment")
    parser.add_argument("--output", help="New result JSON; existing files are never overwritten. Default: stdout.")
    args = parser.parse_args()
    if sys.implementation.name != "cpython" or sys.version_info < (3, 12):
        raise ValueError("This dependency lock requires CPython 3.12 or newer")
    root = Path(__file__).resolve().parent
    checksums = json.loads((root / "SHA256SUMS.json").read_bytes())
    if type(checksums) is not dict or not checksums:
        raise ValueError("Checksum manifest must be a nonempty object")
    required = {"training.json", "result.json", "manifest.json", "rerun.py",
                "requirements.lock", "LICENSE", "THIRD_PARTY_NOTICES.md",
                "phaseglass/coherent.py", "phaseglass/cli.py", "phaseglass/__init__.py"}
    if not required <= set(checksums):
        raise ValueError("Checksum manifest omits required calculation files")
    size = 0
    for name, expected in checksums.items():
        relative = Path(name)
        if type(name) is not str or relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
            raise ValueError("Unsafe checksum path")
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Checksum path leaves bundle")
        data = path.read_bytes()
        size += len(data)
        if size > 4 * 1024 * 1024:
            raise ValueError("Portable contents exceed 4 MiB")
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Checksum mismatch: " + name)
    manifest = json.loads((root / "manifest.json").read_bytes())
    if manifest.get("schema") != "phaseglass-coherent-portable-v1":
        raise ValueError("Unsupported portable schema")
    for key, filename in (("training", "training.json"), ("validation", "validation.json"),
                          ("context", "context.json"), ("result", "result.json")):
        if key not in manifest["canonical_sha256"]:
            continue
        if filename not in checksums:
            raise ValueError("Checksum manifest omits " + filename)
        value = json.loads((root / filename).read_bytes())
        if canonical(value) != manifest["canonical_sha256"][key]:
            raise ValueError("Canonical input/result identity mismatch: " + filename)
    for dependency, expected in (("numpy", "2.3.5"), ("scipy", "1.18.1")):
        try:
            actual = importlib.metadata.version(dependency)
        except importlib.metadata.PackageNotFoundError:
            raise ValueError("Missing dependency " + dependency + "; install requirements.lock") from None
        if actual != expected:
            raise ValueError("Dependency lock mismatch: " + dependency + "=" + actual + "; expected " + expected)
    # Import our own source first. Context/result are never inference arguments.
    sys.path.insert(0, str(root))
    from phaseglass.cli import main as cli_main
    command = "sweep-evaluate" if "validation" in manifest["canonical_sha256"] else "sweep-solve"
    arguments = [command, str(root / "training.json")]
    if command == "sweep-evaluate":
        arguments += ["--validation", str(root / "validation.json")]
    if args.output:
        output = Path(args.output)
        if output.exists() or output.is_symlink():
            raise ValueError("Output already exists; choose a new result path")
        arguments += ["--output", str(output)]
    return cli_main(arguments)

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, TypeError, OSError) as error:
        print("coherent replay: " + str(error), file=sys.stderr)
        raise SystemExit(2)
'''

GUIDE = """# Phaseglass coherent portable experiment

This is synthetic/model-conditioned single-point radio evidence, not a hardware
measurement, room reconstruction, pose tracker or certificate of coherence.

Use CPython 3.12 or newer with an isolated virtual environment. The tested lock is:
    python -m pip install -r requirements.lock
Then run from any working directory:
    python /path/to/bundle/rerun.py --output NEW-result.json
Omit --output to print new JSON to stdout. Existing outputs are refused. result.json
is the calculation freshly recomputed at export; the runner never reads it as fit
input. A rerun may differ in elapsed seconds or minor numerical details.

training.json is the only fitting input. If supplied, validation.json describes
known held receiver positions and IQ tied to the exact canonical training hash.
The held evaluation fits training again, predicts every retained candidate with its
training-fitted complex gains, and neither refits gains/location nor selects/removes
mirror modes using held IQ. Optional context.json is supplied UNVERIFIED context,
never passed to inference. Its presence does not authenticate simulated or measured
provenance. The generator and truth are not required for blind calculations.

Unknown complex gains are assumed constant across receiver positions separately
for each hardware pair and frequency. That assumption and known receiver geometry
are trusted, not established by a small residual. Pose-dependent hardware response
can counterfeit another scene and also pass held-position prediction. Retained
modes are found finite-search candidates, not all mathematical solutions or a
uniqueness/confidence guarantee. Inspect every candidate and the recorded warnings.

SHA256SUMS.json covers all included file bytes except itself. manifest.json records
canonical finite-JSON identities with sorted keys/compact separators. Integral
floats and negative zero share identity with the corresponding integers, matching
browser JSON round trips while the scientific validator still rejects booleans.
The runner
checks these before importing calculation code. They detect changes against this
manifest; they are not signatures or proof of authenticity.

Actual Phaseglass source, MIT LICENSE, and THIRD_PARTY_NOTICES.md are included.
NumPy/SciPy are installed separately under their own licenses. Installing requires
an available package source or local wheel cache; recalculation uses no network.
No account, credential, paid API, telemetry or original scene is required.
"""


def export_sweep(request):
    """Export exact packets and fresh blind results, ignoring supplied results."""
    if type(request) is not dict or "training" not in request:
        raise ValueError("Coherent export requires training")
    if set(request) - {"training", "validation", "context", "result"}:
        raise ValueError("Unknown coherent export fields")
    try:
        raw = encoded(request)
    except (TypeError, RecursionError) as error:
        raise ValueError("Coherent export requires bounded finite JSON") from error
    if len(raw) > MAX_INPUT:
        raise ValueError("Coherent export request exceeds 2 MiB")
    # Freeze plain JSON before fitting, preserving exact packet identities.
    request = decode(raw)
    for key in ("training", "validation", "context"):
        if key in request and type(request[key]) is not dict:
            raise ValueError(key + " must be an object")
    training = request["training"]
    result = (evaluate_sweep(training, request["validation"]) if "validation" in request
              else solve_sweep(training))
    root = resource_root()
    files = {"training.json": encoded(training), "result.json": encoded(result),
             "rerun.py": RUNNER.encode(), "README.md": GUIDE.encode(),
             "requirements.lock": LOCK, "LICENSE": (root / "LICENSE").read_bytes(),
             "THIRD_PARTY_NOTICES.md": (root / "THIRD_PARTY_NOTICES.md").read_bytes()}
    package = Path(__file__).resolve().parent
    for source in sorted(package.glob("*.py")):
        if source.is_symlink() or not source.resolve().is_relative_to(package):
            raise ValueError("Portable source must be a real package file")
        if ":" in source.name or "\\" in source.name:
            raise ValueError("Unsafe portable source filename")
        files["phaseglass/" + source.name] = source.read_bytes()
    identities = {"training": canonical_sha256(training), "result": canonical_sha256(result)}
    for key in ("validation", "context"):
        if key in request:
            files[key + ".json"] = encoded(request[key])
            identities[key] = canonical_sha256(request[key])
    files["manifest.json"] = encoded({
        "schema": "phaseglass-coherent-portable-v1", "version": __version__,
        "canonical_sha256": identities,
        "solver_inputs": ["training.json"] + (["validation.json"] if "validation" in request else []),
        "result_provenance": "fresh-training-fit-then-held-prediction-no-feedback" if "validation" in request else "fresh-blind-training-fit",
        "optional_context": {"present": "context" in request,
                             "status": "supplied-unverified-never-inference-input"},
        "retained_modes": "Every found retained mode is preserved; held IQ never selects or removes modes",
        "coherence_assumption": "unknown complex response per pair/frequency constant across all receiver positions",
        "evidence_scope": "synthetic/model-conditioned point-scatterer; no hardware or coherence certification",
        "replay_runtime": "CPython>=3.12; numpy==2.3.5; scipy==1.18.1",
        "integrity": "Included hashes are not authenticity signatures",
    })
    checksums = encoded({name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())})
    if sum(map(len, files.values())) + len(checksums) > MAX_CONTENTS:
        raise ValueError("Portable coherent contents exceed 4 MiB")
    files["SHA256SUMS.json"] = checksums
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 13, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return output.getvalue()
