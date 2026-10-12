# SPDX-License-Identifier: MIT
"""Portable, source-bearing experiments. Export results are recomputed blindly."""

import hashlib
import io
from pathlib import Path
import zipfile
from . import __version__
from .inverse import solve
from .io import encoded
from .resources import resource_root

RUNNER = '''# SPDX-License-Identifier: MIT
"""Run from anywhere; input is measurement.json, never truth.json."""
from pathlib import Path
import sys
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
from phaseglass.cli import main
if __name__ == "__main__":
    raise SystemExit(main(["solve", str(root / "measurement.json"), *sys.argv[1:]]))
'''

GUIDE = """# Phaseglass portable experiment

Simulation/model-conditioned evidence, not hardware sensing or pose estimation.

Create a virtual environment using Python 3.10 or newer, then install:
    python -m pip install -r requirements.txt
Run the included original blind inverse:
    python rerun.py --output rerun-result.json
Inspect IQ, antennas and bounds in measurement.json. The inverse does not open
scene.json or truth.json. result.json is recomputed by the exporting solver.
Optional scene/truth files are separately supplied context, never solver input.
They are not authenticated claims of measured or generated provenance.

SHA256SUMS.json covers archive file bytes, excluding itself. It detects accidental
changes; it is not a signature or an identity/authenticity guarantee.

The search is finite. Found locations may omit other solutions. Acceptance bands
are heuristics, not confidence probabilities. Unknown hardware phase slopes may
fit well at a wrong location. Local rank does not prove global uniqueness.

Dependencies NumPy and SciPy are installed separately, under their own licenses.
No paid API, account, telemetry, hardware or original simulator is required.
"""


def export_zip(request):
    if type(request) is not dict or "measurement" not in request:
        raise ValueError("Export requires measurement")
    if set(request) - {"measurement", "result", "scene", "truth"}:
        raise ValueError("Unknown export fields")
    measurement = request["measurement"]
    result = solve(measurement)
    root = resource_root()
    files = {
        "measurement.json": encoded(measurement),
        "result.json": encoded(result),
        "rerun.py": RUNNER.encode(),
        "README.md": GUIDE.encode(),
        "requirements.txt": b"numpy>=1.26,<3\nscipy>=1.11,<2\n",
        "LICENSE": (root / "LICENSE").read_bytes(),
        "THIRD_PARTY_NOTICES.md": (root / "THIRD_PARTY_NOTICES.md").read_bytes(),
    }
    for source in sorted(Path(__file__).parent.glob("*.py")):
        files["phaseglass/" + source.name] = source.read_bytes()
    for field in ("scene", "truth"):
        if request.get(field) is not None:
            if type(request[field]) is not dict:
                raise ValueError(field + " must be an object")
            files[field + ".json"] = encoded(request[field])
    files["manifest.json"] = encoded(
        {
            "schema": "phaseglass-portable-v1",
            "version": __version__,
            "solver_input": "measurement.json",
            "solver_result": "result.json",
            "result_provenance": "recomputed-from-measurement-at-export",
            "optional_context": "supplied-unverified-never-inverse-input",
            "simulation_only": True,
        }
    )
    if sum(map(len, files.values())) > 4 * 1024 * 1024:
        raise ValueError("Portable contents exceed 4 MiB")
    files["SHA256SUMS.json"] = encoded(
        {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 12, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return stream.getvalue()
