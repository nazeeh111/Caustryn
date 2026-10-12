# SPDX-License-Identifier: MIT
"""Reproducible studio scenes and separate blind packets, all locally generated."""

import copy
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phaseglass.simulation import simulate

BASE = {
    "name": "mirror-profiled",
    "tx_m": [[0, 0, 0.4], [6, 0, 2.6]],
    "rx_m": [[0, 0, 2.6], [6, 0, 0.4], [3, 0, 1.3]],
    "bounds_m": [[0, 6], [-3, 3], [0, 3]],
    "position_m": [2.371, 1.137, 1.483],
    "carrier_hz": 5.32e9,
    "bandwidth_hz": 20e6,
    "subcarriers": 64,
    "noise_snr_db": 35,
    "gain_mode": "profiled",
    "seed": 128,
    "grid_step_m": 0.2,
}

CASES = [
    (
        "mirror-profiled",
        "The mirror trap",
        "Unknown constant link gains. Two mirrored locations fit the same simulated IQ.",
        {},
    ),
    (
        "mirror-calibrated",
        "Exact symmetry",
        "Noise-free calibrated point. Local rank cannot distinguish a distant mirror.",
        {"noise_snr_db": None, "gain_mode": "calibrated"},
    ),
    (
        "intervention-profiled",
        "Break the symmetry",
        "Move the third receiver off the symmetry plane; regenerate and fit blindly.",
        {"offplane": True},
    ),
    (
        "intervention-calibrated",
        "Calibrated intervention",
        "Known link gains and a moved receiver, with 40 dB simulated SNR.",
        {"offplane": True, "gain_mode": "calibrated", "noise_snr_db": 40},
    ),
    (
        "narrow-noisy",
        "Bandwidth collapses",
        "A 1 MHz band at 20 dB SNR leaves weak spatial constraints.",
        {"offplane": True, "bandwidth_hz": 1e6, "noise_snr_db": 20},
    ),
    (
        "wide-noisy",
        "Restore bandwidth",
        "160 MHz under the same model and noise setting improves local sensitivity.",
        {"offplane": True, "bandwidth_hz": 160e6, "noise_snr_db": 20},
    ),
    (
        "single-frequency-profiled",
        "One tone, no position",
        "One frequency and unknown per-link gains leave a rank-zero family.",
        {"offplane": True, "bandwidth_hz": 0, "subcarriers": 1, "noise_snr_db": None},
    ),
    (
        "missing-receivers",
        "Lose two receivers",
        "Keep one receiver. The inverse shows the resulting underconstrained family.",
        {"rx_m": [BASE["rx_m"][0]]},
    ),
    (
        "unseen-a",
        "Off-grid position A",
        "A separate off-grid point and random noise seed, fit without generator truth.",
        {"offplane": True, "position_m": [4.127, -0.863, 0.927], "seed": 521},
    ),
    (
        "unseen-b",
        "Off-grid position B",
        "Another independent off-grid scene; found modes are not exhaustive.",
        {"offplane": True, "position_m": [1.783, 1.917, 2.231], "seed": 872},
    ),
    (
        "unmodeled-second-reflector",
        "The model breaks",
        "A second scatterer contradicts the single-point model and should trigger refusal.",
        {
            "offplane": True,
            "position_m": [3.183, 1.627, 1.817],
            "seed": 999,
            "extra_reflector": {
                "position_m": [4.263, -0.731, 2.017],
                "gain_real": 0.6 * math.cos(0.83),
                "gain_imag": 0.6 * math.sin(0.83),
            },
        },
    ),
    (
        "unmodeled-hardware-phase-slope",
        "A convincing wrong answer",
        "Unmodeled per-link frequency phase slopes counterfeit another location. Reveal truth to inspect the error.",
        {"offplane": True, "seed": 174, "phase_slope_target_m": [4.427, -1.613, 0.873]},
    ),
]


def main():
    root = Path(__file__).resolve().parents[1] / "examples"
    for name in ("measurements", "scenes", "truth"):
        (root / name).mkdir(parents=True, exist_ok=True)
    rows = []
    for ident, title, description, edits in CASES:
        scene = copy.deepcopy(BASE)
        scene["name"] = ident
        scene.update({key: value for key, value in edits.items() if key != "offplane"})
        if edits.get("offplane"):
            scene["rx_m"][2][1] = 1.1
        sample = simulate(scene)
        rows.append(
            {
                "id": ident,
                "title": title,
                "description": description,
                "scene": scene,
                **sample,
            }
        )
        for folder, item in (
            ("scenes", scene),
            ("measurements", sample["measurement"]),
            ("truth", sample["truth"]),
        ):
            (root / folder / (ident + ".json")).write_text(
                json.dumps(item, indent=2, allow_nan=False) + "\n"
            )
    (root / "studio.json").write_text(
        json.dumps(rows, separators=(",", ":"), allow_nan=False)
    )
    print(
        f"Generated {len(rows)} simulated experiments with separate blind measurements and truth."
    )


if __name__ == "__main__":
    main()
