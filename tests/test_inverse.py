# SPDX-License-Identifier: MIT
import copy
import json
import math
import unittest
from unittest.mock import patch
import numpy as np
from phaseglass import simulate, solve, suggest_intervention
from phaseglass.inverse import validate
from test_simulation import scene


def cases():
    base = scene()
    result = {}

    def add(name, **updates):
        value = copy.deepcopy(base)
        value.update(name=name, **updates)
        result[name] = value

    add("mirror-calibrated", gain_mode="calibrated", noise_snr_db=None)
    add("mirror-profiled")
    moved = copy.deepcopy(base["rx_m"])
    moved[2][1] = 1.1
    add("intervention-calibrated", rx_m=moved, gain_mode="calibrated", noise_snr_db=40)
    add("intervention-profiled", rx_m=moved)
    add("narrow-noisy", rx_m=moved, bandwidth_hz=1e6, noise_snr_db=20)
    add("wide-noisy", rx_m=moved, bandwidth_hz=160e6, noise_snr_db=20)
    add(
        "single-frequency-profiled",
        rx_m=moved,
        subcarriers=1,
        bandwidth_hz=0,
        noise_snr_db=None,
    )
    add("missing-receivers", rx_m=base["rx_m"][:1])
    add("unseen-a", rx_m=moved, position_m=[4.127, -0.863, 0.927], seed=521)
    add("unseen-b", rx_m=moved, position_m=[1.783, 1.917, 2.231], seed=872)
    add(
        "unmodeled-second-reflector",
        rx_m=moved,
        position_m=[3.183, 1.627, 1.817],
        seed=999,
        extra_reflector={
            "position_m": [4.263, -0.731, 2.017],
            "gain_real": 0.6 * math.cos(0.83),
            "gain_imag": 0.6 * math.sin(0.83),
        },
    )
    add(
        "unmodeled-hardware-phase-slope",
        rx_m=moved,
        seed=174,
        phase_slope_target_m=[4.427, -1.613, 0.873],
    )
    return result


class BlindInverseControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generated = {name: simulate(value) for name, value in cases().items()}
        cls.results = {}
        # Disable generator entry point during inverse, exposing accidental calls.
        with patch(
            "phaseglass.simulation.simulate",
            side_effect=AssertionError("truth generator reached by inverse"),
        ):
            for name, generated in cls.generated.items():
                cls.results[name] = solve(generated["measurement"])

    def test_withheld_mirror_and_forced_winner_falsifier(self):
        result = self.results["mirror-calibrated"]
        truth = np.array(self.generated["mirror-calibrated"]["truth"]["position_m"])
        modes = result["candidates"]
        self.assertEqual(len(modes), 2)
        self.assertTrue(all(a["local_jacobian_rank"] == 3 for a in modes))
        self.assertTrue(all(a["relative_iq_residual"] < 1e-9 for a in modes))
        self.assertLess(
            min(np.linalg.norm(np.array(a["position_m"]) - truth) for a in modes), 1e-5
        )
        forced = min(modes, key=lambda a: a["position_m"][1])
        self.assertGreater(np.linalg.norm(np.array(forced["position_m"]) - truth), 2)
        self.assertEqual(self.results["mirror-profiled"]["candidate_count"], 2)

    def test_independent_blind_scenes_and_receiver_intervention(self):
        for name in ("intervention-profiled", "unseen-a", "unseen-b"):
            result = self.results[name]
            truth = self.generated[name]["truth"]["position_m"]
            error = min(math.dist(a["position_m"], truth) for a in result["candidates"])
            self.assertLess(error, 0.15)
            self.assertEqual(result["candidate_count"], 1)
        measurement = self.generated["mirror-calibrated"]["measurement"]
        proposal = suggest_intervention(measurement, self.results["mirror-calibrated"])
        self.assertEqual(proposal["status"], "proposed")
        self.assertEqual(proposal["receiverIndex"], 2)
        self.assertLess(proposal["pairSeparationBefore"], 1e-8)
        self.assertGreater(proposal["pairSeparationAfter"], 0.01)
        self.assertEqual(proposal["search"]["candidateSites"], 225)
        moved = cases()["mirror-calibrated"]
        moved["rx_m"][proposal["receiverIndex"]] = proposal["position_m"]
        final = solve(simulate(moved)["measurement"])
        self.assertEqual(final["candidate_count"], 1)
        self.assertEqual(
            suggest_intervention(
                self.generated["unseen-a"]["measurement"], self.results["unseen-a"]
            )["status"],
            "no-competing-pair",
        )

    def test_missing_links_single_frequency_and_bandwidth_hold(self):
        self.assertEqual(
            self.results["missing-receivers"]["status"], "unidentifiable-family"
        )
        self.assertEqual(
            self.results["missing-receivers"]["best_fit_even_if_refused"][
                "local_jacobian_rank"
            ],
            2,
        )
        single = self.results["single-frequency-profiled"]
        self.assertEqual(single["status"], "unidentifiable-family")
        self.assertEqual(single["best_fit_even_if_refused"]["local_jacobian_rank"], 0)
        self.assertIsNone(single["best_fit_even_if_refused"]["degrees_of_freedom"])
        self.assertEqual(
            self.results["narrow-noisy"]["status"], "weakly-constrained-hold"
        )
        narrow = self.results["narrow-noisy"]["best_fit_even_if_refused"][
            "jacobian_singular_values"
        ][-1]
        wide = self.results["wide-noisy"]["best_fit_even_if_refused"][
            "jacobian_singular_values"
        ][-1]
        self.assertGreater(wide, narrow * 20)

    def test_bad_model_refusal_and_good_fit_bad_truth(self):
        self.assertEqual(
            self.results["unmodeled-second-reflector"]["status"],
            "model-mismatch-or-search-failure",
        )
        slope = self.results["unmodeled-hardware-phase-slope"]
        self.assertLess(slope["best_fit_even_if_refused"]["reduced_chi_squared"], 2)
        truth = self.generated["unmodeled-hardware-phase-slope"]["truth"]["position_m"]
        self.assertGreater(
            min(math.dist(a["position_m"], truth) for a in slope["candidates"]), 2
        )

    def test_coarse_field_is_actual_and_serializes_finitely(self):
        result = self.results["mirror-profiled"]
        field = result["coarse_field"]
        self.assertEqual(
            math.prod(field["shape"]), len(field["profiled_squared_residual"])
        )
        self.assertEqual(result["grid_positions"], 15376)
        self.assertEqual([len(a) for a in field["axes_m"]], field["shape"])
        self.assertIn(None, field["profiled_squared_residual"])
        self.assertTrue(
            all(v is None or v >= 0 for v in field["profiled_squared_residual"])
        )
        for result in self.results.values():
            json.dumps(result, allow_nan=False)

    def test_measurement_rejects_truth_coercion_nonfinite_limits_and_stale_result(self):
        original = self.generated["mirror-profiled"]["measurement"]
        changes = [
            lambda d: d.update({"position_m": [1, 2, 3]}),
            lambda d: d.update({"noise_std_per_component": True}),
            lambda d: d.update({"noise_std_per_component": 1e-300}),
            lambda d: d.update({"grid_step_m": "0.2"}),
            lambda d: d["iq"]["real"][0].__setitem__(0, float("nan")),
            lambda d: d["iq"]["imag"].pop(),
            lambda d: d.update(
                {
                    "iq": {
                        "real": [[0] * 64 for _ in range(6)],
                        "imag": [[0] * 64 for _ in range(6)],
                    }
                }
            ),
            lambda d: d["frequencies_hz"].__setitem__(1, d["frequencies_hz"][0]),
        ]
        for change in changes:
            data = copy.deepcopy(original)
            change(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate(data)
        stale = copy.deepcopy(original)
        stale["rx_m"][2][1] = 1.1
        with self.assertRaises(ValueError):
            suggest_intervention(stale, self.results["mirror-profiled"])
