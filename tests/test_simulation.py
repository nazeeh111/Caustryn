# SPDX-License-Identifier: MIT
import copy
import json
import unittest
from phaseglass import simulate


def scene():
    return {
        "name": "blind off-grid",
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


class SimulationControls(unittest.TestCase):
    def test_reproducible_separate_truth_and_measurement(self):
        a, b = simulate(scene()), simulate(scene())
        self.assertEqual(a, b)
        self.assertEqual(set(a), {"measurement", "truth"})
        self.assertNotIn("position_m", a["measurement"])
        self.assertNotIn("seed", a["measurement"])
        self.assertEqual(a["truth"]["position_m"], scene()["position_m"])
        json.dumps(a, allow_nan=False)

    def test_invalid_scene_types_geometry_resources_and_singularities(self):
        changes = [
            lambda d: d.update({"seed": True}),
            lambda d: d.update({"seed": 10**1000}),
            lambda d: d.update({"subcarriers": "64"}),
            lambda d: d.update({"carrier_hz": float("inf")}),
            lambda d: d["position_m"].__setitem__(0, False),
            lambda d: d.update({"grid_step_m": 0.02}),
            lambda d: d.update({"tx_m": [[0, 0, 0]] * 5}),
            lambda d: d.update({"noise_snr_db": -1}),
            lambda d: d.update({"position_m": [0, 0, 0.4]}),
            lambda d: d.update({"bounds_m": [[0, 40], [-3, 3], [0, 3]]}),
            lambda d: d.update(
                {
                    "extra_reflector": {
                        "position_m": [1, 1, 1],
                        "gain_real": True,
                        "gain_imag": 0,
                    }
                }
            ),
            lambda d: d.update({"phase_slope_target_m": [0, 0, 0.4]}),
            lambda d: d.update({"unrecognized": 1}),
            lambda d: d.update(
                {"tx_m": [[100, 0, 0]] * 4, "rx_m": [[0, 0, 0]] * 4, "subcarriers": 128}
            ),
        ]
        for change in changes:
            data = copy.deepcopy(scene())
            change(data)
            with self.subTest(scene=data), self.assertRaises(ValueError):
                simulate(data)

    def test_extreme_admissible_near_field_scene_returns_solvable_measurement(self):
        data = scene()
        data.update(
            tx_m=[[0, 0, 0]],
            rx_m=[[0, 0, 0]],
            position_m=[0.151, 0, 0],
            noise_snr_db=0,
            subcarriers=1,
            bandwidth_hz=0,
            extra_reflector={
                "position_m": [0.151, 0, 0],
                "gain_real": 2,
                "gain_imag": 2,
            },
        )
        from phaseglass.inverse import validate

        validate(simulate(data)["measurement"])

    def test_frequency_and_single_subcarrier_contract(self):
        data = scene()
        data.update(subcarriers=1, bandwidth_hz=0)
        generated = simulate(data)
        self.assertEqual(generated["measurement"]["frequencies_hz"], [5.32e9])
        self.assertIsNone(generated["truth"]["total_path_delay_scale_m"])
        data["bandwidth_hz"] = 20e6
        with self.assertRaises(ValueError):
            simulate(data)
