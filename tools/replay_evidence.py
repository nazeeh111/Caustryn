# SPDX-License-Identifier: MIT
"""Blind child executions first; independent truth evaluation only afterward."""

import argparse
import cmath
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phaseglass.io import encoded, write_new


def scalar(point, packet):
    rows = []
    for tx in packet["tx_m"]:
        for rx in packet["rx_m"]:
            a, b = math.dist(point, tx), math.dist(point, rx)
            rows.append(
                [
                    cmath.rect(1 / (a * b), -2 * math.pi * f * (a + b) / 299792458)
                    for f in packet["frequencies_hz"]
                ]
            )
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        # Child command receives measurement paths only, not scenes or truth.
        fitted = {}
        for source in sorted((root / "examples/measurements").glob("*.json")):
            output = Path(temp) / source.name
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "phaseglass.cli",
                    "solve",
                    str(source),
                    "--output",
                    str(output),
                ],
                cwd=root,
                check=True,
                timeout=30,
                capture_output=True,
            )
            fitted[source.stem] = json.loads(output.read_text())
        for name, result in fitted.items():
            truth = json.loads((root / "examples/truth" / (name + ".json")).read_text())
            packet_path = root / "examples/measurements" / (name + ".json")
            packet = json.loads(packet_path.read_text())
            candidates = result["candidates"]
            # Evaluate all found candidates. Never choose/retain one using truth.
            errors = [
                math.dist(c["position_m"], truth["position_m"]) for c in candidates
            ]
            best = result["best_fit_even_if_refused"]
            rows.append(
                {
                    "name": name,
                    "status": result["status"],
                    "found_modes": len(candidates),
                    "input_sha256": hashlib.sha256(
                        packet_path.read_bytes()
                    ).hexdigest(),
                    "oracle_only_candidate_errors_m": errors,
                    "relative_iq_residual": best["relative_iq_residual"],
                    "reduced_chi_squared": best["reduced_chi_squared"],
                    "local_rank": best["local_jacobian_rank"],
                }
            )
        packet = json.loads(
            (root / "examples/measurements/mirror-calibrated.json").read_text()
        )
        truth = json.loads(
            (root / "examples/truth/mirror-calibrated.json").read_text()
        )["position_m"]
        mirror = [truth[0], -truth[1], truth[2]]
        original, alternate = scalar(truth, packet), scalar(mirror, packet)
        difference = max(
            abs(a - b)
            for row1, row2 in zip(original, alternate)
            for a, b in zip(row1, row2)
        )
        assert difference == 0
    receipt = {
        "schema": "phaseglass-blind-evidence-v1",
        "simulation_only": True,
        "child_solver_inputs": "measurement paths only; truth evaluated after all fits",
        "independent_scalar_mirror_max_complex_difference": difference,
        "mirror_point_distance_m": math.dist(truth, mirror),
        "experiments": rows,
        "limits": "Finite-search model controls, not measured RF accuracy or all-space uniqueness",
    }
    write_new(args.output, encoded(receipt))
    print(f"Replayed {len(rows)} blind experiments; scalar mirror witness passed.")


if __name__ == "__main__":
    main()
