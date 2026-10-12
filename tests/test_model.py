# SPDX-License-Identifier: MIT
import cmath
import math
import unittest
import numpy as np
from phaseglass.model import channels


class ModelControls(unittest.TestCase):
    def test_scalar_independent_channel_and_exact_mirror(self):
        tx = [[0, 0, 0.4], [6, 0, 2.6]]
        rx = [[0, 0, 2.6], [6, 0, 0.4], [3, 0, 1.3]]
        p = [2.371, 1.137, 1.483]
        mirror = [p[0], -p[1], p[2]]
        frequencies = [5.31e9 + i * 20e6 / 63 for i in range(64)]
        scalar = []
        for t in tx:
            for r in rx:
                dt, dr = math.dist(p, t), math.dist(p, r)
                scalar.append(
                    [
                        cmath.rect(
                            1 / (dt * dr), -2 * math.pi * f * (dt + dr) / 299792458
                        )
                        for f in frequencies
                    ]
                )
        modeled = channels([p, mirror], tx, rx, frequencies)
        np.testing.assert_allclose(modeled[0], scalar, rtol=0, atol=2e-12)
        self.assertTrue(np.array_equal(modeled[0], modeled[1]))
        self.assertGreater(math.dist(p, mirror), 2)
        rx[2][1] = 1.1
        moved = channels([p, mirror], tx, rx, frequencies)
        self.assertGreater(float(np.linalg.norm(moved[0] - moved[1])), 0.01)

    def test_near_antenna_is_excluded_without_division_warning(self):
        with np.errstate(all="raise"):
            values = channels(
                [[0, 0, 0], [0.149, 0, 0], [0.151, 0, 0]],
                [[0, 0, 0]],
                [[1, 0, 0]],
                [5.32e9],
            )
        self.assertTrue(np.isnan(values[:2]).all())
        self.assertTrue(np.isfinite(values[2]).all())
